"""Deterministic detector for solution leaks in a task spec (step 10).

An identifier leaks when it appears in the added lines of the gold patch, does
not appear anywhere in the base repository, and the spec mentions it: the spec
is telling the agent which new names to introduce.
"""

from __future__ import annotations

import re
from pathlib import Path

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")


def detect_leak(spec_text: str, gold_patch: str, base_dir: Path) -> list[str]:
    """Return the sorted identifiers that leak the gold patch into ``spec_text``."""
    introduced = _identifiers_in_added_lines(gold_patch) - _identifiers_in_tree(Path(base_dir))
    mentioned = set(_IDENTIFIER.findall(spec_text))
    return sorted(introduced & mentioned)


def _identifiers_in_added_lines(patch: str) -> set[str]:
    identifiers: set[str] = set()
    for line in patch.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            identifiers.update(_IDENTIFIER.findall(line))
    return identifiers


def _identifiers_in_tree(base_dir: Path) -> set[str]:
    identifiers: set[str] = set()
    for path in base_dir.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        identifiers.update(_IDENTIFIER.findall(text))
    return identifiers
