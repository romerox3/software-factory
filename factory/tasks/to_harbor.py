"""Convert a visible OpenSpec task into the Harbor task format."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import jsonschema

from factory.adapters.config import image_snippet
from factory.adapters.prompt import render_prompt
from factory.tasks.import_hf import REBENCH_ENV_BIN, REBENCH_ENV_PREFIX
from factory.tasks.workdir import DEFAULT_WORKDIR, workdir_of

REPO_ROOT = Path(__file__).resolve().parents[2]
TASK_SCHEMA_PATH = REPO_ROOT / "schemas" / "task.schema.json"

HIDDEN_DIR_NAME = "hidden"
HIDDEN_FILE_NAMES = frozenset({"test.patch", "gold.patch", "f2p.json", "p2p.json", "verifier.json"})
SNAPSHOT_NAME = "snapshot"
SNAPSHOT_GIT_NAME = "snapshot.git"

HOSTNAME_RE = re.compile(r"[A-Za-z0-9.-]+")


def to_harbor(
    visible_task_dir: Path,
    out_dir: Path,
    *,
    executor: str | None = None,
    allowed_hosts: Sequence[str] = (),
    agent_timeout_sec: int | None = None,
) -> Path:
    """Write the Harbor task for ``visible_task_dir`` and return its path.

    ``agent_timeout_sec`` overrides the task's own ``budget.timeout_sec``: the
    matrix measures an arm, so the arm's wall clock must win over the task.
    """
    visible_task_dir = Path(visible_task_dir)
    out_dir = Path(out_dir)
    hosts = _validated_hosts(allowed_hosts)
    agent_timeout = _validated_agent_timeout(agent_timeout_sec)

    task = _load_task(visible_task_dir / "factory.task.json")
    _assert_no_hidden_material(visible_task_dir)

    task_id = task["task_id"]
    target = out_dir / task_id
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ValueError(f"output task directory already exists and is not empty: {target}")

    workdir = workdir_of(task)
    instruction = render_prompt(_build_instruction(visible_task_dir, task_id), workdir)
    task_toml = _build_task_toml(task, hosts, agent_timeout)
    snapshot = _snapshot_git(visible_task_dir)
    if snapshot is None and workdir != DEFAULT_WORKDIR:
        raise ValueError(
            f"{task_id} needs {SNAPSHOT_NAME}/.git for workdir {workdir!r}: "
            "the image's own history must not reach the agent"
        )
    dockerfile = _build_dockerfile(task, workdir, snapshot is not None, executor)
    test_script = _build_test_script(workdir, snapshot_head(visible_task_dir))

    out_dir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(dir=out_dir, prefix=f".{task_id}."))
    try:
        staging.chmod(0o755)
        environment = staging / "environment"
        environment.mkdir()
        (staging / "tests").mkdir()
        (staging / "instruction.md").write_text(instruction, encoding="utf-8")
        (staging / "task.toml").write_text(task_toml, encoding="utf-8")
        (environment / "Dockerfile").write_text(dockerfile, encoding="utf-8")
        if snapshot is not None:
            shutil.copytree(snapshot, environment / SNAPSHOT_GIT_NAME, symlinks=True)
        script_path = staging / "tests" / "test.sh"
        script_path.write_text(test_script, encoding="utf-8")
        script_path.chmod(0o755)
        if target.exists():
            target.rmdir()
        os.replace(staging, target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return target


def tree_digest(path: Path) -> str:
    """Deterministic digest of a converted task tree.

    Covers relative posix paths, file bytes and executable bits, and symlink
    targets; timestamps are ignored so a fresh conversion with the same output
    compares equal to the one on disk.
    """
    root = Path(path)
    entries = sorted(
        ((entry.relative_to(root).as_posix(), entry) for entry in root.rglob("*")),
        key=lambda item: item[0],
    )
    digest = hashlib.sha256()
    for relative, entry in entries:
        if entry.is_symlink():
            kind, payload = b"l", os.readlink(entry).encode("utf-8", errors="surrogateescape")
        elif entry.is_dir():
            kind, payload = b"d", b""
        elif entry.is_file():
            executable = bool(entry.stat().st_mode & stat.S_IXUSR)
            kind, payload = (b"x" if executable else b"f"), entry.read_bytes()
        else:
            raise ValueError(f"unsupported entry in task tree: {entry}")
        digest.update(kind)
        digest.update(relative.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        digest.update(payload)
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _load_task(task_path: Path) -> dict[str, Any]:
    document = json.loads(task_path.read_text(encoding="utf-8"))
    schema = json.loads(TASK_SCHEMA_PATH.read_text(encoding="utf-8"))
    try:
        jsonschema.Draft202012Validator(schema).validate(document)
    except jsonschema.ValidationError as exc:
        raise ValueError(f"{task_path.name} does not match the schema: {exc.message}") from exc
    return document


def _assert_no_hidden_material(task_dir: Path) -> None:
    if task_dir.is_symlink():
        raise ValueError(f"task directory is a symlink: {task_dir}")
    for path in task_dir.rglob("*"):
        if path.relative_to(task_dir).parts[0] == SNAPSHOT_NAME:
            # The snapshot is the repository at the base commit: its files are not
            # task material, and the verifier builds its own checkout anyway.
            continue
        if path.is_symlink():
            raise ValueError(f"task directory contains a symlink: {path}")
        if path.is_dir() and path.name == HIDDEN_DIR_NAME:
            raise ValueError(f"task directory contains a hidden/ directory: {path}")
        if path.is_file() and path.name in HIDDEN_FILE_NAMES:
            raise ValueError(f"task directory contains hidden material: {path}")


def _build_instruction(task_dir: Path, task_id: str) -> str:
    change_dir = task_dir / "openspec" / "changes" / task_id
    parts = [(change_dir / "proposal.md").read_text(encoding="utf-8")]
    specs_dir = change_dir / "specs"
    if specs_dir.is_dir():
        parts.extend(path.read_text(encoding="utf-8") for path in sorted(specs_dir.rglob("*.md")))
    return "\n\n".join(part.strip() for part in parts) + "\n"


def _build_task_toml(
    task: dict[str, Any],
    allowed_hosts: Sequence[str] = (),
    agent_timeout_sec: int | None = None,
) -> str:
    timeout_sec = (
        agent_timeout_sec if agent_timeout_sec is not None else task["budget"]["timeout_sec"]
    )
    if allowed_hosts:
        network = (
            'network_mode = "allowlist"\n'
            "allowed_hosts = [" + ", ".join(f'"{host}"' for host in allowed_hosts) + "]\n"
        )
    else:
        network = 'network_mode = "no-network"\n'
    return (
        'schema_version = "1.4"\n'
        "\n"
        "[agent]\n"
        f"timeout_sec = {timeout_sec}\n"
        "\n"
        "[verifier]\n"
        "timeout_sec = 120.0\n"
        "\n"
        "[environment]\n"
        f"{network}"
        "cpus = 1\n"
        "memory_mb = 2048\n"
    )


def _build_dockerfile(
    task: dict[str, Any], workdir: str, has_snapshot: bool, executor: str | None = None
) -> str:
    """Real images get their history replaced by the fresh-init snapshot (T15)."""
    lines = [f"FROM {task['image']}", ""]
    if workdir != DEFAULT_WORKDIR:
        commit = task["repo"]["commit"]
        lines.append(f"RUN cd {shlex.quote(workdir)} && git checkout -qf {commit} && rm -rf .git")
    if has_snapshot:
        lines.append(f"COPY {SNAPSHOT_GIT_NAME} {workdir}/.git")
    if task["visible_tests"]["command"].startswith(REBENCH_ENV_PREFIX):
        lines.append(f"ENV PATH={REBENCH_ENV_BIN}:$PATH")
    if executor is not None:
        lines.extend(image_snippet(executor))
    lines.append(f"WORKDIR {workdir}")
    return "\n".join(lines) + "\n"


def _validated_agent_timeout(agent_timeout_sec: int | None) -> int | None:
    if agent_timeout_sec is None:
        return None
    if (
        isinstance(agent_timeout_sec, bool)
        or not isinstance(agent_timeout_sec, int)
        or agent_timeout_sec < 1
    ):
        raise ValueError(f"agent_timeout_sec must be an integer >= 1: {agent_timeout_sec!r}")
    return agent_timeout_sec


def _validated_hosts(allowed_hosts: Sequence[str]) -> tuple[str, ...]:
    hosts: list[str] = []
    for host in allowed_hosts:
        if not isinstance(host, str) or not HOSTNAME_RE.fullmatch(host):
            raise ValueError(f"not a bare hostname: {host!r}")
        hosts.append(host)
    return tuple(hosts)


def _snapshot_git(task_dir: Path) -> Path | None:
    """Return the ``.git`` of the fresh-init snapshot, if the task has one."""
    snapshot = task_dir / SNAPSHOT_NAME / ".git"
    return snapshot if snapshot.is_dir() else None


def snapshot_head(task_dir: Path) -> str:
    """Commit id of the task snapshot, or ``HEAD`` when there is no usable snapshot."""
    snapshot = Path(task_dir) / SNAPSHOT_NAME
    if not snapshot.is_dir():
        return "HEAD"
    try:
        completed = subprocess.run(
            ["git", "-C", str(snapshot), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return "HEAD"
    commit = completed.stdout.strip()
    return commit if completed.returncode == 0 and commit else "HEAD"


def _build_test_script(workdir: str, base_commit: str) -> str:
    """Write the diff and a constant reward; never run the visible suite here.

    Harbor's verifier has a fixed 120 s timeout and its reward is not a verdict:
    the factory verifier decides on the host. A slow visible suite would hit
    ``VerifierTimeoutError`` and lose the agent's diff, so ``test.sh`` only
    exports the patch and writes a reward that says nothing about the outcome.
    """
    checkout = shlex.quote(workdir)
    base = shlex.quote(base_commit)
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "\n"
        "mkdir -p /logs/verifier\n"
        "\n"
        "if ! ("
        f"cd {checkout} && git add -A && git diff --cached --binary {base}"
        " > /logs/verifier/diff.patch); then\n"
        "  : > /logs/verifier/diff.patch\n"
        "fi\n"
        "\n"
        "echo 0 > /logs/verifier/reward.txt\n"
    )
