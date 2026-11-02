"""T29: the sealed result stream, forced with a fake sandbox so every branch is reachable."""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

import pytest

from factory.verifier import RunRequest, RunResult, engine, verify

from .support import (
    TOKEN,
    FakeSandbox,
    frame,
    junit_xml,
    make_ts_store,
    stream_bytes,
    stream_lines,
)
from .test_failclosed import F2P, all_passed, check, dotted, writes


def stream_run(stdout: bytes, cases: dict[str, str] | None = None, **result: object):
    """A run whose JUnit report is clean and whose stdout is ``stdout``."""
    return writes(cases or all_passed(), stdout=stdout, **result)


def test_a_run_without_the_result_stream_is_never_an_accept(py_mirror) -> None:
    verdict = check(FakeSandbox(stream_run(b"")), py_mirror)
    assert (verdict.verdict, verdict.category) == ("reject", "junit_missing")


def test_the_run_gets_the_plugin_in_a_read_only_mount_under_an_unpredictable_name(
    py_mirror,
) -> None:
    seen: dict[str, object] = {}

    def behavior(request: RunRequest) -> RunResult:
        ((directory, target),) = request.read_only_mounts
        files = sorted(path.name for path in directory.iterdir())
        seen.update(target=target, files=files, env=dict(request.env))
        seen["mode"] = directory.stat().st_mode
        seen["source"] = (directory / files[0]).read_bytes()
        return writes(all_passed())(request)

    verdict = check(FakeSandbox(behavior), py_mirror)
    assert verdict.verdict == "accept", verdict.reason
    (name,) = seen["files"]  # type: ignore[misc]
    module = name.removesuffix(".py")
    assert module.startswith("fv_") and len(module) == 19
    env = seen["env"]
    assert env["PYTHONPATH"] == seen["target"] == "/opt/factory-verifier"  # type: ignore[index]
    assert env["PYTEST_ADDOPTS"] == f"-p {module} -p no:cacheprovider"  # type: ignore[index]
    assert seen["source"] == engine.PLUGIN_SOURCE.read_bytes()
    assert seen["mode"] & 0o022 == 0  # type: ignore[operator]  # only the owner can write


def test_the_verifier_never_imports_the_plugin_it_ships() -> None:
    """Importing it would dup fd 1 of the verifier's own process and print a hello line."""
    assert "factory.verifier.runner_plugin" not in sys.modules


def test_a_report_that_passes_what_the_stream_failed_is_a_cheat(py_mirror) -> None:
    """The T29 exploit: the stream (append-only, outside) knows the F2P ids failed."""
    cases = all_passed()
    cases[dotted(F2P[0])] = "failed"
    behavior = writes(all_passed(), stdout=stream_bytes(cases), exit_code=0)
    verdict = check(FakeSandbox(behavior), py_mirror)
    assert (verdict.verdict, verdict.category) == ("cheat_suspected", "junit_forged")
    assert "claims a pass" in verdict.reason


def test_a_stream_that_passes_what_the_report_failed_is_not_an_accept(py_mirror) -> None:
    cases = all_passed()
    cases[dotted(F2P[0])] = "failed"
    behavior = writes(cases, stdout=stream_bytes(all_passed()))
    verdict = check(FakeSandbox(behavior), py_mirror)
    assert (verdict.verdict, verdict.category) == ("reject", "junit_invalid")


def test_a_missing_report_is_a_reject_even_with_a_clean_stream(py_mirror) -> None:
    def behavior(request: RunRequest) -> RunResult:
        return RunResult(exit_code=0, stdout=stream_bytes(all_passed()))

    verdict = check(FakeSandbox(behavior), py_mirror)
    assert (verdict.verdict, verdict.category) == ("reject", "junit_missing")


def line_edit(old: str, new: str):
    def mutate(lines: list[str]) -> list[str]:
        return [line.replace(old, new, 1) if old in line else line for line in lines]

    return mutate


FORGERIES = {
    "frame with another token": lambda lines: [
        *lines[:-1],
        frame("f" * 32, t="r", id="x", when="call", o="passed", x=False),
        lines[-1],
    ],
    "frame before the hello": lambda lines: [lines[1], *lines],
    "second hello": lambda lines: [lines[0], *lines],
    "frame after the end": lambda lines: [
        *lines,
        frame(t="r", id="x", when="call", o="passed", x=False),
    ],
    "second end": lambda lines: [*lines, lines[-1]],
    "duplicated phase": lambda lines: [lines[0], lines[1], *lines[1:]],
    "end that miscounts the frames": line_edit('"frames":', '"frames":1'),
    "end without an integer exit": line_edit('"exit":0', '"exit":"0"'),
    "not json": lambda lines: [*lines[:-1], "FV:" + TOKEN + ":{oops", lines[-1]],
    "unknown frame type": lambda lines: [*lines[:-1], frame(t="zzz"), lines[-1]],
    "tripwire that passed": lambda lines: [
        line.replace('"o":"failed"', '"o":"passed"') if "tripwire" in line else line
        for line in lines
    ],
}


@pytest.mark.parametrize("name", sorted(FORGERIES))
def test_a_tampered_stream_is_a_cheat_even_when_the_report_is_perfect(py_mirror, name) -> None:
    stdout = ("\n".join(FORGERIES[name](stream_lines(all_passed()))) + "\n").encode()
    verdict = check(FakeSandbox(stream_run(stdout)), py_mirror)
    assert verdict.verdict == "cheat_suspected", (name, verdict.reason)
    assert verdict.category == "junit_forged"


def test_a_clean_run_that_lacks_the_tripwire_is_a_cheat(py_mirror) -> None:
    without = stream_bytes(all_passed(), tripwire=None)
    verdict = check(FakeSandbox(stream_run(without)), py_mirror)
    assert (verdict.verdict, verdict.category) == ("cheat_suspected", "junit_forged")


def test_a_stream_that_never_ends_is_a_reject_not_an_accept(py_mirror) -> None:
    unfinished = ("\n".join(stream_lines(all_passed())[:-1]) + "\n").encode()
    verdict = check(FakeSandbox(stream_run(unfinished)), py_mirror)
    assert (verdict.verdict, verdict.category) == ("reject", "junit_missing")


def test_a_truncated_stream_is_a_reject(py_mirror) -> None:
    run = stream_run(stream_bytes(all_passed()), stdout_truncated=True)
    verdict = check(FakeSandbox(run), py_mirror)
    assert (verdict.verdict, verdict.category) == ("reject", "junit_invalid")


def test_unframed_output_is_ignored(py_mirror) -> None:
    noise = ["...........", "FV in the middle is not a frame", "9 passed in 0.1s"]
    lines = [noise[0], *stream_lines(all_passed())[:3], noise[1], *stream_lines(all_passed())[3:]]
    stdout = ("\n".join([*lines, noise[2]]) + "\n").encode()
    verdict = check(FakeSandbox(stream_run(stdout)), py_mirror)
    assert verdict.verdict == "accept", verdict.reason


def test_pytest_ending_non_zero_after_the_end_frame_is_not_an_accept(py_mirror) -> None:
    """The stream says pytest itself ended with 1 although every expected id passed."""
    run = stream_run(stream_bytes(all_passed(), exit_status=1), exit_code=0)
    verdict = check(FakeSandbox(run), py_mirror)
    assert verdict.verdict == "reject"


def test_an_exit_code_forged_to_zero_cannot_hide_a_failing_run(py_mirror) -> None:
    """``os._exit(0)`` from an atexit hook: the container says 0, the stream says 1."""
    cases = all_passed()
    cases[dotted(F2P[0])] = "failed"
    run = writes(cases, stdout=stream_bytes(cases, exit_status=1), exit_code=0)
    verdict = check(FakeSandbox(run), py_mirror)
    assert (verdict.verdict, verdict.category) == ("reject", "hidden_checks_failed")


def test_jest_keeps_the_junit_only_channel_and_gets_no_plugin(ts_mirror) -> None:
    """Residual risk of T29 for jest/vitest, documented in docs/05: no plugin, the report decides."""

    def behavior(request: RunRequest) -> RunResult:
        assert request.read_only_mounts == () and request.env == ()
        found = re.search(r"/logs/verifier/report-[0-9a-f]+\.xml", request.command)
        assert found is not None
        xml = junit_xml({"src/extra.test.ts::extra": "passed"})
        (request.logs_dir / Path(found.group(0)).name).write_text(xml, encoding="utf-8")
        return RunResult(exit_code=0)

    store = make_ts_store(Path(tempfile.mkdtemp()))
    diff = (
        b"--- a/src/calc.ts\n+++ b/src/calc.ts\n@@ -1,3 +1,4 @@\n+// harmless\n"
        b" /** Toy calculator used as a fixture repository. */\n \n"
        b" export function add(a: number, b: number): number {\n"
    )
    verdict = verify(
        store,
        "ts-calc-task",
        diff,
        ts_mirror[0],
        run=None,
        sandbox=FakeSandbox(behavior),
        attempt=1,
        base_commit=ts_mirror[1],
    )
    assert verdict.verdict == "accept", verdict.reason


def ts_verdict(ts_mirror, xml: str):
    """Verify the harmless ts diff against a jest task whose report is ``xml``."""

    def behavior(request: RunRequest) -> RunResult:
        found = re.search(r"/logs/verifier/report-[0-9a-f]+\.xml", request.command)
        assert found is not None
        (request.logs_dir / Path(found.group(0)).name).write_text(xml, encoding="utf-8")
        return RunResult(exit_code=0)

    store = make_ts_store(Path(tempfile.mkdtemp()))
    diff = (
        b"--- a/src/calc.ts\n+++ b/src/calc.ts\n@@ -1,3 +1,4 @@\n+// harmless\n"
        b" /** Toy calculator used as a fixture repository. */\n \n"
        b" export function add(a: number, b: number): number {\n"
    )
    return verify(
        store,
        "ts-calc-task",
        diff,
        ts_mirror[0],
        run=None,
        sandbox=FakeSandbox(behavior),
        attempt=1,
        base_commit=ts_mirror[1],
    )


JEST_CASE = "<testcase classname='src/extra.test.ts' name='extra' />"


def test_a_jest_report_repeating_a_passing_id_is_an_accept(ts_mirror) -> None:
    verdict = ts_verdict(ts_mirror, f"<testsuites>{JEST_CASE}{JEST_CASE}</testsuites>")
    assert verdict.verdict == "accept", verdict.reason


def test_a_jest_report_repeating_an_id_keeps_the_failing_copy(ts_mirror) -> None:
    """One passing copy must never hide the failing one: the merge keeps the worst status."""
    failed_case = (
        "<testcase classname='src/extra.test.ts' name='extra'><failure message='x'/></testcase>"
    )
    verdict = ts_verdict(ts_mirror, f"<testsuites>{JEST_CASE}{failed_case}</testsuites>")
    assert verdict.verdict == "reject"
