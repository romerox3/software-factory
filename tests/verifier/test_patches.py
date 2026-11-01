"""Hostile patches and the verdict schema: nothing here may end in an accept or in error_infra."""

from __future__ import annotations

import copy

import jsonschema
import pytest

from factory.verifier import RunResult, verify
from factory.verifier.verdict import validate_document

from .support import TASKS, FakeSandbox

ROUND = "py-calc-round"


def new_file(path: str, body: str = "x = 1\n", mode: str = "100644") -> bytes:
    return (
        f"diff --git a/{path} b/{path}\nnew file mode {mode}\n--- /dev/null\n+++ b/{path}\n"
        f"@@ -0,0 +1 @@\n+{body}"
    ).encode()


def run_patch(py_mirror, diff: bytes):
    fake = FakeSandbox(lambda request: RunResult(exit_code=0))
    return verify(
        TASKS / ROUND,
        ROUND,
        diff,
        py_mirror[0],
        run=None,
        sandbox=fake,
        attempt=1,
        base_commit=py_mirror[1],
    )


@pytest.mark.parametrize(
    "path",
    [".git/hooks/pre-commit", "../outside.py", "/abs/outside.py", "src/../../outside.py"],
)
def test_paths_that_escape_or_touch_git_are_rejected(py_mirror, path) -> None:
    verdict = run_patch(py_mirror, new_file(path))
    assert verdict.verdict == "reject"
    assert verdict.category in {"patch_invalid", "diff_guard"}


def test_a_diff_with_hundreds_of_files_is_patch_invalid(py_mirror) -> None:
    diff = b"".join(new_file(f"src/calc/m{i}.py") for i in range(301))
    verdict = run_patch(py_mirror, diff)
    assert (verdict.verdict, verdict.category) == ("reject", "patch_invalid")


def test_a_new_executable_script_outside_the_blocked_places_is_not_a_mode_change(
    py_mirror,
) -> None:
    verdict = run_patch(py_mirror, new_file("src/calc/tool.py", mode="100755"))
    # No rule fires; the (fake) run has no report, so it is rejected for that and only that.
    assert verdict.category == "junit_missing"


def test_a_diff_that_only_touches_whitespace_is_not_empty(py_mirror) -> None:
    verdict = run_patch(py_mirror, b"\n\n")
    assert verdict.category == "empty_diff"


GOOD = {
    "schema_version": "1",
    "run_id": "r",
    "task_id": "abc-1",
    "arm": "A1",
    "attempt": 1,
    "repetition": 0,
    "verdict": "reject",
    "reason": "x",
    "verify_cost_usd": 0.0,
    "diff_sha": "sha256:" + "0" * 64,
    "category": "timeout",
}
ACCEPT = {
    **GOOD,
    "verdict": "accept",
    "isolated": True,
    "hard": {},
    "hashes": {k: "sha256:" + "1" * 64 for k in ("diff", "test_patch", "verifier", "image")},
}
del ACCEPT["category"]


def mutated(base: dict, **changes: object) -> dict:
    document = copy.deepcopy(base)
    document.update(changes)
    return {k: v for k, v in document.items() if v is not None}


def test_schema_accepts_the_reference_documents() -> None:
    validate_document(GOOD)
    validate_document(ACCEPT)


@pytest.mark.parametrize(
    "document",
    [
        mutated(GOOD, verdict="accept_flaky"),
        mutated(GOOD, category=None),  # a reject needs its category
        mutated(GOOD, diff_sha="abc"),
        mutated(GOOD, attempt=0),
        mutated(GOOD, extra=1),
        mutated(ACCEPT, isolated=False),
        mutated(ACCEPT, category="timeout"),
        mutated(ACCEPT, hashes={"diff": "sha256:" + "1" * 64}),
        mutated(ACCEPT, hashes={**ACCEPT["hashes"], "image": None}),
        mutated(ACCEPT, isolated=None),
        mutated(
            GOOD, feedback={"items": [{"type": "hidden_checks", "message": "expected 42 got 41"}]}
        ),
        mutated(GOOD, feedback={"items": [{"type": "trace", "text": "AssertionError"}]}),
        mutated(GOOD, rule_ids=["tests/test_calc.py::test_secret"]),
    ],
)
def test_schema_rejects_what_would_break_a_guarantee(document) -> None:
    with pytest.raises(jsonschema.ValidationError):
        validate_document(document)
