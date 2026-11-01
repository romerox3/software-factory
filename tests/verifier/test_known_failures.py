"""Accept rule with the pre-existing failures recorded by revalidation.

``hidden/<task>/known_failures.json`` lists the tests that fail at base and at gold. Their
failure is expected, so it neither rejects the diff nor blocks the accept through the exit
code; any other failing test still rejects, and the sealed stream is still required.
"""

from __future__ import annotations

import json
from pathlib import Path

from factory.verifier import RunRequest, RunResult, verify
from factory.verifier.taskstore import load_task

from .support import (
    TASKS,
    FakeSandbox,
    copy_store,
    junit_xml,
    load_json,
    report_path,
    stream_bytes,
    stream_lines,
)

ROUND = "py-calc-round"
HIDDEN = TASKS / ROUND / "hidden" / ROUND
GOLD = (HIDDEN / "gold.patch").read_bytes()
F2P = load_json(HIDDEN / "f2p.json")
P2P = load_json(HIDDEN / "p2p.json")
KNOWN = "tests/test_known_broken.py::test_always_fails"


def dotted(node_id: str) -> str:
    path, _, name = node_id.partition("::")
    return f"{path.removesuffix('.py').replace('/', '.')}::{name}"


def all_passed() -> dict[str, str]:
    return {dotted(test_id): "passed" for test_id in [*F2P, *P2P]}


def writes(
    cases: dict[str, str], *, exit_code: int = 0, sealed_exit: int | None = None, **result: object
):
    """A run that writes the JUnit report and the matching sealed result stream."""
    exit_status = exit_code if sealed_exit is None else sealed_exit

    def behavior(request: RunRequest) -> RunResult:
        report_path(request).write_text(junit_xml(cases), encoding="utf-8")
        return RunResult(
            exit_code=exit_code,
            stdout=stream_bytes(cases, exit_status=exit_status),
            **result,  # type: ignore[arg-type]
        )

    return behavior


def store_with_known(tmp_path: Path, known: list[str]) -> Path:
    store = copy_store(ROUND, tmp_path / "store")
    (store / "hidden" / ROUND / "known_failures.json").write_text(
        json.dumps(known), encoding="utf-8"
    )
    return store


def check(sandbox, py_mirror, store: Path, diff: bytes = GOLD):
    return verify(
        store,
        ROUND,
        diff,
        py_mirror[0],
        run=None,
        sandbox=sandbox,
        attempt=1,
        base_commit=py_mirror[1],
    )


def test_taskstore_reads_known_failures_and_defaults_to_empty(tmp_path: Path) -> None:
    assert load_task(TASKS / ROUND, ROUND).known_failures == ()
    store = store_with_known(tmp_path, [KNOWN])
    assert load_task(store, ROUND).known_failures == (KNOWN,)


def test_a_known_failure_failing_with_exit_code_1_is_an_accept(py_mirror, tmp_path) -> None:
    cases = {**all_passed(), dotted(KNOWN): "failed"}
    store = store_with_known(tmp_path, [KNOWN])

    verdict = check(FakeSandbox(writes(cases, exit_code=1)), py_mirror, store)

    assert verdict.verdict == "accept", verdict.reason
    assert verdict.diagnostics["known_failures"] == 1
    assert verdict.diagnostics["known_failures_in_report"] == 1


def test_exit_code_2_rejects_even_with_known_failures(py_mirror, tmp_path) -> None:
    cases = {**all_passed(), dotted(KNOWN): "failed"}
    store = store_with_known(tmp_path, [KNOWN])

    verdict = check(FakeSandbox(writes(cases, exit_code=2)), py_mirror, store)

    assert verdict.verdict == "reject"
    assert verdict.category == "hidden_checks_failed"


def test_a_sealed_exit_status_2_rejects_with_a_container_exit_of_1(py_mirror, tmp_path) -> None:
    cases = {**all_passed(), dotted(KNOWN): "failed"}
    store = store_with_known(tmp_path, [KNOWN])

    verdict = check(FakeSandbox(writes(cases, exit_code=1, sealed_exit=2)), py_mirror, store)

    assert verdict.verdict == "reject"
    assert verdict.category == "hidden_checks_failed"


def test_a_killed_container_rejects_even_with_known_failures(py_mirror, tmp_path) -> None:
    cases = {**all_passed(), dotted(KNOWN): "failed"}
    store = store_with_known(tmp_path, [KNOWN])

    verdict = check(FakeSandbox(writes(cases, exit_code=137)), py_mirror, store)

    assert verdict.verdict == "reject"
    assert verdict.category == "hidden_checks_failed"


def test_a_known_failure_that_now_passes_is_not_a_reject(py_mirror, tmp_path) -> None:
    cases = {**all_passed(), dotted(KNOWN): "passed"}
    store = store_with_known(tmp_path, [KNOWN])

    verdict = check(FakeSandbox(writes(cases)), py_mirror, store)

    assert verdict.verdict == "accept", verdict.reason


def test_a_new_unlisted_failure_still_rejects(py_mirror, tmp_path) -> None:
    cases = {
        **all_passed(),
        dotted(KNOWN): "failed",
        "tests.test_other::test_new": "failed",
    }
    store = store_with_known(tmp_path, [KNOWN])

    verdict = check(FakeSandbox(writes(cases, exit_code=1)), py_mirror, store)

    assert verdict.verdict == "reject"
    assert verdict.category == "hidden_checks_failed"


def test_an_empty_list_keeps_rejecting_a_non_zero_exit(py_mirror, tmp_path) -> None:
    store = store_with_known(tmp_path, [])

    verdict = check(FakeSandbox(writes(all_passed(), exit_code=1)), py_mirror, store)

    assert verdict.verdict == "reject"
    assert verdict.category == "hidden_checks_failed"


def test_the_sealed_stream_is_still_required_with_known_failures(py_mirror, tmp_path) -> None:
    cases = {**all_passed(), dotted(KNOWN): "failed"}
    store = store_with_known(tmp_path, [KNOWN])

    def no_end_frame(request: RunRequest) -> RunResult:
        report_path(request).write_text(junit_xml(cases), encoding="utf-8")
        lines = stream_lines(cases, exit_status=1)[:-1]
        return RunResult(exit_code=1, stdout=("\n".join(lines) + "\n").encode())

    verdict = check(FakeSandbox(no_end_frame), py_mirror, store)

    assert (verdict.verdict, verdict.category) == ("reject", "junit_missing")


def test_a_green_tripwire_is_still_a_forgery_with_known_failures(py_mirror, tmp_path) -> None:
    cases = {**all_passed(), dotted(KNOWN): "failed"}
    store = store_with_known(tmp_path, [KNOWN])

    def green_tripwire(request: RunRequest) -> RunResult:
        report_path(request).write_text(junit_xml(cases), encoding="utf-8")
        stream = stream_bytes(cases, exit_status=1, tripwire="passed")
        return RunResult(exit_code=1, stdout=stream)

    verdict = check(FakeSandbox(green_tripwire), py_mirror, store)

    assert (verdict.verdict, verdict.category) == ("cheat_suspected", "junit_forged")
