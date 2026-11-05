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
SECTION_START = re.compile(rb"(?m)^diff --git ")
FACTORY_DIR = ".factory"
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


def split_factory_files(patch: bytes) -> tuple[bytes, dict[str, bytes]]:
    """Remove every ``.factory/`` file section and return the added contents.

    ``<workdir>/.factory/`` is the harness/agent side channel (prompt, abort
    document), not part of the candidate change: it must never reach the
    verifier or the stored diff. The rest of the patch is kept byte for byte.
    """
    starts = [match.start() for match in SECTION_START.finditer(patch)]
    if not starts:
        return patch, {}
    parts = [patch[: starts[0]]]
    factory_files: dict[str, bytes] = {}
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(patch)
        section = patch[start:end]
        path = _section_path(section)
        if path is not None and path.startswith(FACTORY_DIR + "/"):
            factory_files[path] = _added_content(section)
        else:
            parts.append(section)
    return b"".join(parts), factory_files


def _section_path(section: bytes) -> str | None:
    header = section.split(b"\n", 1)[0]
    match = re.fullmatch(rb"diff --git a/(.+) b/(.+)", header)
    if match is None:
        return None
    try:
        return match.group(2).decode("utf-8")
    except UnicodeDecodeError:
        return None


def _added_content(section: bytes) -> bytes:
    """The file a section adds, rebuilt from its ``+`` lines."""
    content = b""
    in_hunk = False
    last_was_added = False
    for line in section.split(b"\n"):
        if line.startswith(b"@@"):
            in_hunk = True
            last_was_added = False
        elif in_hunk and line.startswith(b"+"):
            content += line[1:] + b"\n"
            last_was_added = True
        elif in_hunk and line == b"\\ No newline at end of file":
            if last_was_added and content.endswith(b"\n"):
                content = content[:-1]
            last_was_added = False
        else:
            last_was_added = False
    return content


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
