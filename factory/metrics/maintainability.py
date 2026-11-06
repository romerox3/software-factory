"""Maintainability deltas for a diff: M7a (complexity) and M7b (duplication).

A base source tree plus a unified diff define an "after" tree. The touched
source files are measured on both sides with lizard: cyclomatic complexity and
NLOC of the touched functions for M7a, and duplicated blocks reported by
lizard's duplicate extension for M7b.

``measure`` is the only function that works on trees: it copies the base,
applies the diff and runs the analysis. ``parse_diff`` is pure and maps the
changed line numbers to both sides of each file.
"""

from __future__ import annotations

import re
import statistics
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import lizard
from lizard import get_extensions
from lizard_core.analysis import analyze_files

from factory.miner.split import is_test_path
from factory.verifier.gitops import apply_patch, copy_tree

# lizard's duplicate extension CLI default, used by ``get_duplicates()``
MIN_DUPLICATE_TOKENS = 70

_HUNK = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@"
)


@dataclass(frozen=True, slots=True)
class FileDelta:
    """Line numbers changed by a diff, per side of one file."""

    path: str
    added: frozenset[int]
    deleted: frozenset[int]


@dataclass(frozen=True, slots=True)
class MaintainabilityDelta:
    """M7a and M7b deltas between the after and before trees."""

    ccn_max: int
    ccn_mean: float
    nloc: int
    new_dup_blocks: int


def parse_diff(diff: bytes | str) -> tuple[FileDelta, ...]:
    """Return the added and deleted line numbers of every file in ``diff``."""
    text = diff.decode("utf-8", "surrogateescape") if isinstance(diff, bytes) else diff
    changes: list[FileDelta] = []
    old_path: str | None = None
    new_path: str | None = None
    added: set[int] = set()
    deleted: set[int] = set()
    old_line = new_line = 0
    in_hunk = False

    def flush() -> None:
        nonlocal old_path, new_path, added, deleted, in_hunk
        path = new_path or old_path
        if path is not None and (added or deleted):
            changes.append(FileDelta(path, frozenset(added), frozenset(deleted)))
        old_path = new_path = None
        added, deleted = set(), set()
        in_hunk = False

    for line in text.splitlines():
        if line.startswith("diff --git "):
            flush()
            continue
        match = _HUNK.match(line)
        if match is not None:
            old_line = int(match.group("old_start"))
            new_line = int(match.group("new_start"))
            in_hunk = True
            continue
        if in_hunk:
            if line.startswith("+"):
                added.add(new_line)
                new_line += 1
            elif line.startswith("-"):
                deleted.add(old_line)
                old_line += 1
            elif line.startswith(" ") or line == "":
                old_line += 1
                new_line += 1
            else:
                in_hunk = False
            continue
        if line.startswith("--- "):
            old_path = _header_path(line[4:])
        elif line.startswith("+++ "):
            new_path = _header_path(line[4:])
    flush()
    return tuple(changes)


def measure(base: Path, diff: bytes | str) -> MaintainabilityDelta:
    """Materialize ``diff`` on a copy of ``base`` and measure M7a and M7b.

    Raises ``ValueError`` when the diff does not apply to ``base``.
    """
    base = Path(base)
    changes = [change for change in parse_diff(diff) if not is_test_path(change.path)]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        after = root / "after"
        _apply(base, diff, after, root)
        return _measure(base, after, changes)


def _apply(base: Path, diff: bytes | str, dest: Path, tmp: Path) -> None:
    copy_tree(base, dest)
    patch = tmp / "change.patch"
    patch.write_bytes(diff.encode("utf-8", "surrogateescape") if isinstance(diff, str) else diff)
    home = tmp / "home"
    home.mkdir()
    if not apply_patch(dest, patch, home, check_only=False):
        raise ValueError(f"diff does not apply to {base}")


def _measure(before: Path, after: Path, changes: Sequence[FileDelta]) -> MaintainabilityDelta:
    paths = [change.path for change in changes]
    before_infos = _infos(before, paths)
    after_infos = _infos(after, paths)

    touched: set[tuple[str, str]] = set()
    for change in changes:
        side = before_infos.get(change.path)
        if side is not None:
            touched |= _touched_keys(change.path, side, change.deleted)
        side = after_infos.get(change.path)
        if side is not None:
            touched |= _touched_keys(change.path, side, change.added)

    before_functions = _functions(before_infos, touched)
    after_functions = _functions(after_infos, touched)
    before_ccn = [function.cyclomatic_complexity for function in before_functions]
    after_ccn = [function.cyclomatic_complexity for function in after_functions]

    return MaintainabilityDelta(
        ccn_max=max(after_ccn, default=0) - max(before_ccn, default=0),
        ccn_mean=_mean(after_ccn) - _mean(before_ccn),
        nloc=sum(function.nloc for function in after_functions)
        - sum(function.nloc for function in before_functions),
        new_dup_blocks=_duplicate_blocks(after, after_infos)
        - _duplicate_blocks(before, before_infos),
    )


def _infos(root: Path, paths: Iterable[str]) -> dict[str, Any]:
    infos: dict[str, Any] = {}
    for path in dict.fromkeys(paths):
        full = root / path
        if not full.is_file():
            continue
        info = _analyze(full)
        if info is not None:
            infos[path] = info
    return infos


def _analyze(path: Path) -> Any | None:
    try:
        info = lizard.analyze_file(str(path))
    except (IndexError, UnicodeDecodeError, OSError):
        return None
    return info if info.token_count else None


def _touched_keys(path: str, info: Any, lines: frozenset[int]) -> set[tuple[str, str]]:
    return {
        (path, function.long_name)
        for function in info.function_list
        if any(function.start_line <= line <= function.end_line for line in lines)
    }


def _functions(infos: Mapping[str, Any], touched: Iterable[tuple[str, str]]) -> list[Any]:
    functions: list[Any] = []
    for path, name in touched:
        info = infos.get(path)
        if info is None:
            continue
        functions.extend(function for function in info.function_list if function.long_name == name)
    return functions


def _mean(values: Sequence[int]) -> float:
    return statistics.fmean(values) if values else 0.0


def _duplicate_blocks(root: Path, infos: Mapping[str, Any]) -> int:
    files = [str(root / path) for path in sorted(infos)]
    if not files:
        return 0
    extensions = get_extensions(["duplicate"])
    list(analyze_files(files, 1, extensions))
    finder = next(extension for extension in extensions if hasattr(extension, "get_duplicates"))
    return sum(1 for _ in finder.get_duplicates(min_duplicate_tokens=MIN_DUPLICATE_TOKENS))


def _header_path(raw: str) -> str | None:
    name = raw.split("\t", 1)[0].strip()
    if name == "/dev/null":
        return None
    if name.startswith(("a/", "b/")):
        return name[2:]
    return name
