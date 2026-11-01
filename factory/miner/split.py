"""Split a PR diff into its code patch and its test patch.

The heuristic comes from the mining recipe (docs/06-harness-and-tasks.md §2.2,
step 3): a file is a test file when one of its path segments is ``test``,
``tests``, ``e2e``, ``testing`` or ``__tests__``, or when its name matches
``*.spec.*`` or ``*.test.*``. Each file is moved whole to one side.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

_TEST_SEGMENTS = frozenset({"test", "tests", "e2e", "testing", "__tests__"})
_TEST_NAME_MARKERS = (".spec.", ".test.")

_DIFF_GIT = re.compile(r"^diff --git a/(?P<old>\S+) b/(?P<new>\S+)")
_DIFF_NEW_FILE = re.compile(r"^\+\+\+ b/(?P<new>\S+)")


def split_patch(diff: str) -> tuple[str, str]:
    """Return ``(code_patch, test_patch)`` for a unified git diff."""
    code: list[str] = []
    tests: list[str] = []
    for chunk in _chunks(diff):
        target = tests if is_test_path(_chunk_path(chunk)) else code
        target.append(chunk)
    return "".join(code), "".join(tests)


def is_test_path(path: str) -> bool:
    """Whether ``path`` belongs to the test patch under the mining heuristic."""
    parts = PurePosixPath(path).parts
    if any(part.lower() in _TEST_SEGMENTS for part in parts[:-1]):
        return True
    name = parts[-1].lower() if parts else ""
    return any(marker in name for marker in _TEST_NAME_MARKERS)


def _chunks(diff: str) -> list[str]:
    """Split ``diff`` into per-file chunks, keeping line endings intact."""
    chunks: list[list[str]] = []
    current: list[str] | None = None
    for line in diff.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if current is not None:
                chunks.append(current)
            current = [line]
        elif current is not None:
            current.append(line)
    if current is not None:
        chunks.append(current)
    if not chunks:
        return _chunks_without_git_header(diff)
    return ["".join(lines) for lines in chunks]


def _chunks_without_git_header(diff: str) -> list[str]:
    """Fallback for plain unified diffs that lack ``diff --git`` headers."""
    chunks: list[list[str]] = []
    current: list[str] | None = None
    for line in diff.splitlines(keepends=True):
        if line.startswith("--- ") and not line.startswith("--- /dev/null"):
            if current is not None:
                chunks.append(current)
            current = [line]
        elif current is not None:
            current.append(line)
    if current is not None:
        chunks.append(current)
    return ["".join(lines) for lines in chunks]


def _chunk_path(chunk: str) -> str:
    match = _DIFF_GIT.search(chunk)
    if match is not None:
        return match.group("new")
    match = _DIFF_NEW_FILE.search(chunk)
    return match.group("new") if match is not None else ""
