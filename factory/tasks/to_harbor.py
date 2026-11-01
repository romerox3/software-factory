"""Convert a visible OpenSpec task into the Harbor task format."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import tempfile
from pathlib import Path
from typing import Any

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
TASK_SCHEMA_PATH = REPO_ROOT / "schemas" / "task.schema.json"

HIDDEN_DIR_NAME = "hidden"
HIDDEN_FILE_NAMES = frozenset({"test.patch", "gold.patch", "f2p.json", "p2p.json", "verifier.json"})


def to_harbor(visible_task_dir: Path, out_dir: Path) -> Path:
    """Write the Harbor task for ``visible_task_dir`` and return its path."""
    visible_task_dir = Path(visible_task_dir)
    out_dir = Path(out_dir)

    task = _load_task(visible_task_dir / "factory.task.json")
    _assert_no_hidden_material(visible_task_dir)

    task_id = task["task_id"]
    target = out_dir / task_id
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ValueError(f"output task directory already exists and is not empty: {target}")

    instruction = _build_instruction(visible_task_dir, task_id)
    task_toml = _build_task_toml(task)
    dockerfile = _build_dockerfile(task["image"])
    test_script = _build_test_script(task["visible_tests"]["command"])

    out_dir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(dir=out_dir, prefix=f".{task_id}."))
    try:
        staging.chmod(0o755)
        (staging / "environment").mkdir()
        (staging / "tests").mkdir()
        (staging / "instruction.md").write_text(instruction, encoding="utf-8")
        (staging / "task.toml").write_text(task_toml, encoding="utf-8")
        (staging / "environment" / "Dockerfile").write_text(dockerfile, encoding="utf-8")
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


def _build_task_toml(task: dict[str, Any]) -> str:
    timeout_sec = task["budget"]["timeout_sec"]
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
        'network_mode = "no-network"\n'
        "cpus = 1\n"
        "memory_mb = 2048\n"
    )


def _build_dockerfile(image: str) -> str:
    return f"FROM {image}\n\nWORKDIR /workspace\n"


def _build_test_script(command: str) -> str:
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "\n"
        "mkdir -p /logs/verifier\n"
        "\n"
        f"if bash -c {shlex.quote(command)}; then\n"
        "  echo 1 > /logs/verifier/reward.txt\n"
        "else\n"
        "  echo 0 > /logs/verifier/reward.txt\n"
        "fi\n"
    )
