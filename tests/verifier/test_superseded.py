"""A new file that the hidden ``test.patch`` also creates is superseded, not rejected."""

from __future__ import annotations

import json
from pathlib import Path

from factory.verifier import RunRequest, RunResult, verify

from .support import (
    TASKS,
    FakeSandbox,
    copy_store,
    edit_verifier,
    junit_xml,
    load_json,
    report_path,
    stream_bytes,
)

ROUND = "py-calc-round"
HIDDEN = TASKS / ROUND / "hidden" / ROUND
GOLD = (HIDDEN / "gold.patch").read_bytes()
P2P = load_json(HIDDEN / "p2p.json")

CREATED = "tests/test_round_hidden.py"
F2P = [
    "tests/test_round_hidden.py::test_ties_up",
    "tests/test_round_hidden.py::test_ties_with_ndigits",
]
CREATED_PATCH = b"""diff --git a/tests/test_round_hidden.py b/tests/test_round_hidden.py
new file mode 100644
--- /dev/null
+++ b/tests/test_round_hidden.py
@@ -0,0 +1,9 @@
+from calc import round_half_up
+
+
+def test_ties_up() -> None:
+    assert round_half_up(2.5) == 3
+
+
+def test_ties_with_ndigits() -> None:
+    assert round_half_up(0.125, 2) == 0.13
"""
TEST_COMMAND = (
    "python -m pytest -q tests/test_calc.py tests/test_round_hidden.py "
    "--junitxml=/logs/verifier/junit.xml"
)


def new_file(path: str, body: str = "x = 1\n") -> bytes:
    return (
        f"diff --git a/{path} b/{path}\nnew file mode 100644\n--- /dev/null\n+++ b/{path}\n"
        f"@@ -0,0 +1 @@\n+{body}"
    ).encode()


def dotted(node_id: str) -> str:
    path, _, name = node_id.partition("::")
    return f"{path.removesuffix('.py').replace('/', '.')}::{name}"


def writes(cases: dict[str, str]):
    """A run that writes the JUnit report and the matching sealed result stream."""

    def behavior(request: RunRequest) -> RunResult:
        report_path(request).write_text(junit_xml(cases), encoding="utf-8")
        return RunResult(exit_code=0, stdout=stream_bytes(cases))

    return behavior


def store_creating_a_test(tmp_path: Path) -> Path:
    """``py-calc-round`` but with a hidden ``test.patch`` that creates a new test file."""
    store = copy_store(ROUND, tmp_path / "store")
    hidden = store / "hidden" / ROUND
    (hidden / "test.patch").write_bytes(CREATED_PATCH)
    (hidden / "f2p.json").write_text(json.dumps(F2P), encoding="utf-8")
    edit_verifier(store, ROUND, test_command=TEST_COMMAND)
    return store


def check(store: Path, py_mirror, diff: bytes, sandbox, task_id: str = ROUND):
    return verify(
        store,
        task_id,
        diff,
        py_mirror[0],
        run=None,
        sandbox=sandbox,
        attempt=1,
        base_commit=py_mirror[1],
    )


def test_a_new_file_the_hidden_patch_creates_is_superseded_and_decided_by_it(
    py_mirror, tmp_path
) -> None:
    store = store_creating_a_test(tmp_path)
    cases = {dotted(test_id): "passed" for test_id in [*F2P, *P2P]}

    verdict = check(store, py_mirror, GOLD + new_file(CREATED), FakeSandbox(writes(cases)))

    assert verdict.verdict == "accept", verdict.reason
    assert verdict.rule_ids == []
    assert verdict.informative["superseded_by_hidden"] == [CREATED]


def test_modifying_a_file_the_hidden_patch_touches_is_still_forbidden(py_mirror) -> None:
    diff = b"""diff --git a/tests/test_calc.py b/tests/test_calc.py
--- a/tests/test_calc.py
+++ b/tests/test_calc.py
@@ -1,3 +1,3 @@
-\"\"\"Visible tests for the toy calculator.\"\"\"
+\"\"\"Visible tests for the toy calculator (edited).\"\"\"
 
 import pytest
"""
    verdict = check(
        TASKS / ROUND, py_mirror, diff, FakeSandbox(lambda request: RunResult(exit_code=0))
    )

    assert verdict.verdict == "reject"
    assert verdict.category == "diff_guard"
    assert "dg.forbidden-glob" in verdict.rule_ids


def test_a_diff_that_only_creates_the_superseded_file_is_empty(py_mirror, tmp_path) -> None:
    store = store_creating_a_test(tmp_path)

    verdict = check(
        store, py_mirror, new_file(CREATED), FakeSandbox(lambda request: RunResult(exit_code=0))
    )

    assert (verdict.verdict, verdict.category) == ("reject", "empty_diff")
    assert verdict.informative["superseded_by_hidden"] == [CREATED]


def test_a_canary_keeps_the_strict_diff_guard_for_the_same_diff(canary_store, py_mirror) -> None:
    diff = new_file("tests/test_round_canary.py", body="x = 1\n")

    verdict = check(
        canary_store,
        py_mirror,
        diff,
        FakeSandbox(lambda request: RunResult(exit_code=0)),
        task_id="py-calc-canary",
    )

    assert (verdict.verdict, verdict.category) == ("cheat_suspected", "diff_guard")
    assert "dg.forbidden-glob" in verdict.rule_ids
    assert verdict.informative["superseded_by_hidden"] == []
