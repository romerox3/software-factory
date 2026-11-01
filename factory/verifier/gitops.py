"""Git plumbing for the verifier: clean checkout, patch application and change listing.

Everything here runs on the host, on throwaway repositories created by the verifier. The
change list comes from ``git diff --raw -z`` / ``--numstat -z`` after the candidate diff was
applied and staged with ``git add -A -f``, so it never depends on how the diff is written.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

from factory.snapshot.fresh_init import build_snapshot
from factory.verifier.diffguard import Change

GIT_TIMEOUT_S = 120
# Applied before anything in the tree: ``info/attributes`` has the highest precedence, so a
# ``.gitattributes`` that sneaks in cannot enable filters, eol rewriting or diff drivers.
NEUTRAL_ATTRIBUTES = "* -text -ident -filter -merge !diff\n"
MAX_ADDED_LINES_PER_FILE = 5000
MAX_FILES = 300


class InfraError(RuntimeError):
    """A failure of the verifier's own infrastructure, never caused by the candidate diff."""


class PatchError(ValueError):
    """The candidate diff cannot be applied or parsed."""


def git_env(home: Path) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key in {"PATH", "LANG", "TMPDIR"}}
    env.update(
        {
            "HOME": str(home),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
            "LC_ALL": "C",
        }
    )
    return env


def run_git(
    args: Sequence[str], repo: Path, home: Path, *, stdin: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    command = ["git", "-c", "core.autocrlf=false", "-c", "core.fsmonitor=false", *args]
    return subprocess.run(
        command,
        cwd=repo,
        env=git_env(home),
        input=stdin,
        capture_output=True,
        check=False,
        timeout=GIT_TIMEOUT_S,
    )


def _git_ok(args: Sequence[str], repo: Path, home: Path) -> bytes:
    result = run_git(args, repo, home)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", "replace").strip()[:300]
        raise InfraError(f"git {' '.join(args[:2])} failed: {stderr}")
    return result.stdout


def clean_checkout(mirror: Path, commit: str, dest: Path) -> str:
    """Materialize ``commit`` of ``mirror`` as a fresh single-commit repo in ``dest``."""
    mirror = Path(mirror)
    if not mirror.is_dir():
        raise InfraError(f"mirror not found: {mirror}")
    try:
        sha = build_snapshot(mirror, commit, dest)
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        raise InfraError(f"cannot build a clean checkout of {commit}: {exc}") from exc
    info = dest / ".git" / "info"
    info.mkdir(parents=True, exist_ok=True)
    (info / "attributes").write_text(NEUTRAL_ATTRIBUTES, encoding="utf-8")
    return sha


def apply_patch(repo: Path, patch_file: Path, home: Path, *, check_only: bool) -> bool:
    """Run ``git apply`` for ``patch_file``; return True when git accepts it."""
    args = ["apply", "--whitespace=nowarn"]
    if check_only:
        args.append("--check")
    args += ["--", str(patch_file)]
    return run_git(args, repo, home).returncode == 0


def stage_everything(repo: Path, home: Path) -> None:
    _git_ok(["add", "-A", "-f"], repo, home)


def list_changes(repo: Path, home: Path) -> list[Change]:
    """Changes staged in ``repo`` against ``HEAD``, with modes, binary flag and added lines."""
    raw = _git_ok(
        ["diff", "--cached", "--raw", "-z", "--no-renames", "--no-abbrev", "--no-ext-diff"],
        repo,
        home,
    )
    numstat = _git_ok(
        ["diff", "--cached", "--numstat", "-z", "--no-renames", "--no-ext-diff"], repo, home
    )
    stats: dict[str, tuple[bool, int, int]] = {}
    for record in numstat.split(b"\0"):
        if not record:
            continue
        fields = record.split(b"\t", 2)
        if len(fields) != 3:
            raise PatchError("unparseable numstat record")
        path = fields[2].decode("utf-8", "surrogateescape")
        if fields[0] == b"-" and fields[1] == b"-":
            stats[path] = (True, 0, 0)
        else:
            stats[path] = (False, int(fields[0]), int(fields[1]))

    if len(stats) > MAX_FILES:
        raise PatchError(f"the diff touches more than {MAX_FILES} files")
    tokens = raw.split(b"\0")
    changes: list[Change] = []
    index = 0
    while index < len(tokens) and tokens[index]:
        meta = tokens[index].decode("ascii", "replace")
        if not meta.startswith(":") or index + 1 >= len(tokens):
            raise PatchError("unparseable raw diff record")
        old_mode, new_mode, _old_sha, _new_sha, status = meta[1:].split(" ")
        path = tokens[index + 1].decode("utf-8", "surrogateescape")
        index += 2
        if status not in {"A", "M", "D", "T"}:
            raise PatchError(f"unsupported change status {status!r}")
        if path not in stats:
            raise PatchError("raw and numstat listings disagree")
        binary, added, deleted = stats[path]
        lines: tuple[str, ...] = ()
        if not binary and status != "D":
            lines = _added_lines(repo, home, path)
        changes.append(
            Change(
                path=path,
                status=status,
                old_mode=old_mode,
                new_mode=new_mode,
                binary=binary,
                added_lines=lines,
                added=added,
                deleted=deleted,
            )
        )
    if len(changes) != len(stats):
        raise PatchError("raw and numstat listings disagree")
    return changes


def _added_lines(repo: Path, home: Path, path: str) -> tuple[str, ...]:
    raw_path = path.encode("utf-8", "surrogateescape")
    result = run_git(
        [
            "diff",
            "--cached",
            "--no-renames",
            "--no-ext-diff",
            "--no-textconv",
            "--text",
            "-U0",
            "--no-color",
            "--",
            ":(literal)" + raw_path.decode("utf-8", "surrogateescape"),
        ],
        repo,
        home,
    )
    if result.returncode != 0:
        raise InfraError("git diff failed while reading added lines")
    out: list[str] = []
    in_hunks = False
    for line in result.stdout.decode("utf-8", "replace").split("\n"):
        if line.startswith("@@"):
            in_hunks = True
        elif in_hunks and line.startswith("+"):
            out.append(line[1:])
            if len(out) >= MAX_ADDED_LINES_PER_FILE:
                break
    return tuple(out)


def copy_tree(source: Path, dest: Path) -> None:
    """Copy the working tree of ``source`` to ``dest`` without ``.git``, keeping symlinks as is."""
    shutil.copytree(
        source,
        dest,
        symlinks=True,
        ignore=shutil.ignore_patterns(".git"),
        dirs_exist_ok=False,
    )


def open_permissions(root: Path) -> None:
    """Make ``root`` writable for the unprivileged user that runs the container."""
    for path in [root, *root.rglob("*")]:
        if path.is_symlink():
            continue
        mode = 0o777 if path.is_dir() else 0o666
        path.chmod(mode | (0o111 if path.is_file() and os.access(path, os.X_OK) else 0))
