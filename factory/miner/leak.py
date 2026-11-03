"""Deterministic detector for solution leaks in a task spec (step 10).

An identifier leaks when it appears as code in the added lines of the gold patch,
does not appear anywhere in the base repository, and the spec mentions it: the
spec is telling the agent which new names to introduce. Names declared by the
task itself (its ``## Interface`` section) are not leaks, and prose additions
(comments, docstrings, changelogs) introduce no code identifiers.
"""

from __future__ import annotations

import io
import re
import textwrap
import tokenize
from pathlib import Path

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")
_PROSE_SUFFIXES = frozenset({".md", ".rst", ".txt"})
_PROSE_NAMES = ("CHANGELOG", "NEWS", "HISTORY")
_STRING_LITERAL = re.compile(
    r"(?:[rRbBuUfF]{0,2})"
    r"(?:\"\"\".*?\"\"\"|'''.*?'''|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')"
)


def detect_leak(
    spec_text: str, gold_patch: str, base_dir: Path, *, declared: str = ""
) -> list[str]:
    """Return the sorted identifiers that leak the gold patch into ``spec_text``.

    Identifiers named in ``declared`` (the task's ``## Interface`` section) are
    never reported: the hidden tests call them, so announcing them is not a leak.
    """
    introduced = _identifiers_in_added_lines(gold_patch) - _identifiers_in_tree(Path(base_dir))
    mentioned = set(_IDENTIFIER.findall(spec_text))
    announced = set(_IDENTIFIER.findall(declared))
    return sorted((introduced & mentioned) - announced)


def _identifiers_in_added_lines(patch: str) -> set[str]:
    """Collect the identifiers the patch adds as code, file by file."""
    identifiers: set[str] = set()
    path: str | None = None
    block: list[str] | None = None
    in_hunk = False

    def flush_block() -> None:
        nonlocal block
        if block is None:
            return
        if _is_prose(path):
            pass
        elif path is not None and path.endswith(".py"):
            identifiers.update(_python_names("\n".join(block)))
        else:
            for line in block:
                identifiers.update(_IDENTIFIER.findall(line))
        block = None

    for line in patch.splitlines():
        if line.startswith("diff --git "):
            flush_block()
            path, in_hunk = _diff_git_path(line), False
        elif line.startswith("@@"):
            flush_block()
            in_hunk = True
        elif not in_hunk and line.startswith(("--- ", "+++ ")):
            flush_block()
            header_path = _patch_path(line[4:])
            if header_path is not None:
                path = header_path
        elif line.startswith("+"):
            if block is None:
                block = []
            block.append(line[1:])
        elif in_hunk:
            flush_block()
            if line != "" and not line.startswith((" ", "-", "\\")):
                in_hunk = False
    flush_block()
    return identifiers


def _is_prose(path: str | None) -> bool:
    """Tell whether ``path`` is documentation: its added lines carry no code."""
    if path is None:
        return False
    name = Path(path).name
    return Path(path).suffix.lower() in _PROSE_SUFFIXES or name.upper().startswith(_PROSE_NAMES)


def _python_names(block: str) -> set[str]:
    """Return the NAME tokens of an added Python block, docstrings and comments aside."""
    text = textwrap.dedent(block)
    try:
        tokens = tokenize.generate_tokens(io.StringIO(text).readline)
        names = {token.string for token in tokens if token.type == tokenize.NAME}
    except (tokenize.TokenError, IndentationError, SyntaxError):
        names = _names_without_prose(text)
    return {name for name in names if _IDENTIFIER.fullmatch(name)}


def _names_without_prose(text: str) -> set[str]:
    """Fallback for untokenizable fragments: strip string literals and comments per line."""
    names: set[str] = set()
    for line in text.splitlines():
        code = _STRING_LITERAL.sub(" ", line)
        names.update(_IDENTIFIER.findall(code.split("#", 1)[0]))
    return names


def _patch_path(raw: str) -> str | None:
    """Normalize a ``---``/``+++`` path, ignoring timestamps and ``/dev/null``."""
    token = raw.strip().split("\t", 1)[0].strip()
    if len(token) > 1 and token.startswith('"') and token.endswith('"'):
        token = token[1:-1]
    if token == "/dev/null":
        return None
    if token.startswith(("a/", "b/")):
        token = token[2:]
    return token or None


def _diff_git_path(line: str) -> str | None:
    parts = line.split()
    return _patch_path(parts[-1]) if len(parts) > 2 else None


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
