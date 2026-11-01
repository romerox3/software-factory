"""Compute the candidate diff on the host from an exported workspace.

The agent's ``.git`` is discarded and replaced by the snapshot's, so its config
(hooks, filters, ``diff.external``) cannot influence the result. The snapshot's
``info/attributes`` is replaced by neutral attributes, which also cancels any
``.gitattributes`` in the working tree (threat T30). Git runs with no global or
system configuration and with external diff and textconv disabled.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from factory.verifier.gitops import NEUTRAL_ATTRIBUTES, copy_tree, run_git

COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
# ``-c diff.external=`` unsets the external diff driver; the snapshot's config
# never sets it, but an input mistake must not turn into an executed command.
ISOLATED_CONFIG = (
    "-c",
    "core.attributesFile=/dev/null",
    "-c",
    "diff.external=",
    "-c",
    "core.hooksPath=/dev/null",
)


@dataclass(frozen=True)
class HostDiff:
    """The binary patch and the numbers the output schema asks for."""

    patch: bytes
    sha256: str
    files_changed: int
    lines_added: int
    lines_removed: int


def compute_diff(workspace: str | Path, snapshot_git: str | Path, base_commit: str) -> HostDiff:
    """Diff ``workspace`` against ``base_commit`` using the snapshot's ``.git``."""
    workspace = Path(workspace)
    snapshot_git = Path(snapshot_git)
    if not workspace.is_dir():
        raise ValueError(f"exported workspace is not a directory: {workspace}")
    if not snapshot_git.is_dir():
        raise ValueError(f"snapshot .git is not a directory: {snapshot_git}")
    if not COMMIT_SHA.fullmatch(base_commit):
        raise ValueError(f"base commit must be a 40-character sha: {base_commit!r}")

    with tempfile.TemporaryDirectory(prefix="factory-diff-") as tmp:
        root = Path(tmp)
        work = root / "work"
        home = root / "home"
        home.mkdir()
        copy_tree(workspace, work)
        shutil.copytree(snapshot_git, work / ".git", symlinks=True)
        info = work / ".git" / "info"
        info.mkdir(parents=True, exist_ok=True)
        (info / "attributes").write_text(NEUTRAL_ATTRIBUTES, encoding="utf-8")

        _git([*ISOLATED_CONFIG, "add", "-A", "-f"], work, home)
        patch = _git(
            [
                *ISOLATED_CONFIG,
                "diff",
                "--cached",
                "--binary",
                "--no-ext-diff",
                "--no-textconv",
                "--no-renames",
                "--no-color",
                base_commit,
            ],
            work,
            home,
        )
        numstat = _git(
            [
                *ISOLATED_CONFIG,
                "diff",
                "--cached",
                "--numstat",
                "-z",
                "--no-renames",
                base_commit,
            ],
            work,
            home,
        )

    files_changed, lines_added, lines_removed = _totals(numstat)
    return HostDiff(
        patch=patch,
        sha256="sha256:" + hashlib.sha256(patch).hexdigest(),
        files_changed=files_changed,
        lines_added=lines_added,
        lines_removed=lines_removed,
    )


def empty_diff() -> HostDiff:
    """The diff of a run that produced no change (abort, budget kill, error)."""
    return HostDiff(
        patch=b"",
        sha256="sha256:" + hashlib.sha256(b"").hexdigest(),
        files_changed=0,
        lines_added=0,
        lines_removed=0,
    )


def _git(args: list[str], repo: Path, home: Path) -> bytes:
    result = run_git(args, repo, home)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", "replace").strip()[:300]
        raise RuntimeError(f"git {' '.join(args[:3])} failed: {stderr}")
    return result.stdout


def _totals(numstat: bytes) -> tuple[int, int, int]:
    files = added = removed = 0
    for record in numstat.split(b"\0"):
        if not record:
            continue
        fields = record.split(b"\t", 2)
        if len(fields) != 3:
            raise RuntimeError("unparseable numstat record")
        files += 1
        if fields[0] == b"-" and fields[1] == b"-":
            continue
        added += int(fields[0])
        removed += int(fields[1])
    return files, added, removed
