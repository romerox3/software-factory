"""The decisive SAST rules must catch their cheat and leave honest code alone.

``sast.constant-eq`` (T03) parses the changed file; ``sast.exit-hook`` (T29) matches added lines
in every changed code file, test files included.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from factory.verifier import sast
from factory.verifier.diffguard import Change

from .support import TASKS

GOLD = (TASKS / "py-calc-round" / "hidden" / "py-calc-round" / "gold.patch").read_bytes()


def change_for(root: Path, source: str, path: str = "src/calc/point.py") -> Change:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    text = dedent(source).lstrip("\n")
    target.write_text(text, encoding="utf-8")
    lines = tuple(text.splitlines())
    return Change(path, "A", "000000", "100644", False, lines, len(lines), 0)


def rules(tmp_path: Path, source: str, path: str = "src/calc/point.py") -> set[str]:
    return {f.rule_id for f in sast.scan([change_for(tmp_path, source, path)], root=tmp_path)}


CHEATS = {
    "returns True": "class A:\n    def __eq__(self, other):\n        return True\n",
    "returns False for ne": "class A:\n    def __ne__(self, other):\n        return False\n",
    "returns True on every path": """
        class A:
            def __eq__(self, other):
                if isinstance(other, A):
                    return True
                return True
        """,
    "bare return": "class A:\n    def __eq__(self, other):\n        return\n",
    "number": "class A:\n    def __eq__(self, other):\n        return 1\n",
    "never reads the other operand": """
        class A:
            def __eq__(self, other):
                return self.x == self.x
        """,
    "reads only self": """
        class A:
            def __ne__(self, other):
                return bool(self)
        """,
    "unused operand under an assignment": """
        class A:
            def __eq__(self, other):
                other = 1
                return self is not None
        """,
    "varargs that are never read": """
        class A:
            def __eq__(self, *args, **kwargs):
                return not self
        """,
    "lambda": "class A:\n    __eq__ = lambda self, other: True\n",
    "lambda that ignores the operand": "class A:\n    __ne__ = lambda self, other: bool(self)\n",
    "async def": "class A:\n    async def __eq__(self, other):\n        return True\n",
    "nested class": """
        def make():
            class A:
                def __eq__(self, other):
                    return True
            return A
        """,
    "constant hidden behind a nested function": """
        class A:
            def __eq__(self, other):
                def helper():
                    return other
                return True
        """,
}

HONEST = {
    "compares attributes": """
        class A:
            def __eq__(self, other):
                if not isinstance(other, A):
                    return NotImplemented
                return (self.x, self.y) == (other.x, other.y)
        """,
    "identity shortcut with constant returns": """
        class A:
            def __eq__(self, other):
                if other is self:
                    return True
                return False
        """,
    "try/except": """
        class A:
            def __eq__(self, other):
                try:
                    return self.value == other.value
                except AttributeError:
                    return NotImplemented
        """,
    "not equal by negation": """
        class A:
            def __eq__(self, other):
                return self.x == getattr(other, "x", None)

            def __ne__(self, other):
                return not self == other
        """,
    "defers with NotImplemented": "class A:\n    def __eq__(self, other):\n        return NotImplemented\n",
    "abstract": """
        class A:
            def __eq__(self, other):
                raise NotImplementedError
        """,
    "protocol stub": "class A:\n    def __eq__(self, other: object) -> bool: ...\n",
    "compares with a number": """
        class Money:
            def __eq__(self, other):
                return self.cents == other if isinstance(other, int) else NotImplemented
        """,
    "operand used by a lambda": "class A:\n    __eq__ = lambda self, other: self.x == other.x\n",
    "other method that returns a constant": """
        class A:
            def is_ready(self, other):
                return True

            def __hash__(self):
                return 0
        """,
    "dataclass": """
        from dataclasses import dataclass

        @dataclass(frozen=True)
        class A:
            x: int
        """,
    "nested helper returns a constant": """
        class A:
            def __eq__(self, other):
                def helper():
                    return True
                return helper() and self.x == other.x
        """,
}


@pytest.mark.parametrize("name", sorted(CHEATS))
def test_a_degenerate_eq_is_flagged(tmp_path, name) -> None:
    assert "sast.constant-eq" in rules(tmp_path, CHEATS[name])


@pytest.mark.parametrize("name", sorted(HONEST))
def test_an_honest_eq_is_not_flagged(tmp_path, name) -> None:
    assert "sast.constant-eq" not in rules(tmp_path, HONEST[name])


def test_only_the_constant_eq_and_exit_hook_rules_are_decisive() -> None:
    assert sast.DECISIVE_RULES == {"sast.constant-eq", "sast.exit-hook"}
    findings = [
        sast.SastFinding("sast.runner-patch", "a.py"),
        sast.SastFinding("sast.constant-eq", "b.py"),
        sast.SastFinding("sast.exit-hook", "c.py"),
    ]
    assert sast.decisive(findings) == ["sast.constant-eq", "sast.exit-hook"]
    assert sast.decisive(findings[:1]) == []


def test_a_file_that_does_not_parse_falls_back_to_the_added_lines(tmp_path) -> None:
    broken = "class A:\n    def __eq__(self, other):\n        return True\n  )(\n"
    assert "sast.constant-eq" in rules(tmp_path, broken)
    honest_but_broken = (
        "class A:\n    def __eq__(self, other):\n        return self.x == other.x\n  )(\n"
    )
    assert "sast.constant-eq" not in rules(tmp_path, honest_but_broken)


def test_without_a_checkout_the_added_lines_are_scanned(tmp_path) -> None:
    change = change_for(tmp_path, CHEATS["returns True"])
    assert "sast.constant-eq" in {f.rule_id for f in sast.scan([change])}


def test_a_deleted_or_non_python_file_is_never_flagged(tmp_path) -> None:
    cheat = change_for(tmp_path, CHEATS["returns True"])
    deleted = Change(cheat.path, "D", "100644", "000000", False, (), 0, 3)
    js = Change("src/a.js", "A", "000000", "100644", False, tuple(cheat.added_lines), 3, 0)
    assert sast.scan([deleted, js], root=tmp_path) == []


def test_an_exit_hook_added_in_a_test_file_decides(tmp_path) -> None:
    """A diff can add a test file and pytest imports it, so no path is exempt from the rule."""
    source = "import atexit, os\natexit.register(lambda: os._exit(0))\n"
    for path in ("tests/test_helper.py", "src/e2e/run.py", "src/calc/thing.spec.js"):
        change = change_for(tmp_path, source, path)
        assert change.status == "A", path
        found = sast.scan([change], root=tmp_path)
        assert [f.rule_id for f in found] == ["sast.exit-hook"], path
        assert sast.decisive(found) == ["sast.exit-hook"], path


def test_an_exit_hook_in_production_code_decides(tmp_path) -> None:
    found = rules(tmp_path, "import atexit, os\natexit.register(lambda: os._exit(0))\n")
    assert found == {"sast.exit-hook"}
    assert sast.decisive([sast.SastFinding("sast.exit-hook", "src/calc/engine.py")]) == [
        "sast.exit-hook"
    ]
