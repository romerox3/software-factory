"""Fail-closed behaviour, forced with a fake sandbox so every branch is reachable and fast."""

from __future__ import annotations

from pathlib import Path

import pytest

from factory.verifier import DockerSandbox, RunRequest, RunResult, SandboxError, verify
from factory.verifier import sandbox as sandbox_module
from factory.verifier.verdict import validate_document

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
F2P = load_json(HIDDEN / "f2p.json")
P2P = load_json(HIDDEN / "p2p.json")


def dotted(node_id: str) -> str:
    path, _, name = node_id.partition("::")
    return f"{path.removesuffix('.py').replace('/', '.')}::{name}"


def all_passed() -> dict[str, str]:
    return {dotted(test_id): "passed" for test_id in [*F2P, *P2P]}


def writes(content: str | dict[str, str], *, exit_code: int = 0, **result: object):
    """A run that writes the JUnit report and, for a dict, the matching sealed result stream."""

    def behavior(request: RunRequest) -> RunResult:
        text = junit_xml(content) if isinstance(content, dict) else content
        report_path(request).write_text(text, encoding="utf-8")
        if isinstance(content, dict) and "stdout" not in result:
            result["stdout"] = stream_bytes(content, exit_status=exit_code)
        return RunResult(exit_code=exit_code, **result)  # type: ignore[arg-type]

    return behavior


def check(
    sandbox,
    py_mirror,
    diff: bytes = GOLD,
    store: Path | None = None,
    run: dict | None = None,
    **kwargs,
):
    return verify(
        store or TASKS / ROUND,
        ROUND,
        diff,
        py_mirror[0],
        run=run,
        sandbox=sandbox,
        attempt=1,
        base_commit=py_mirror[1],
        **kwargs,
    )


def test_a_clean_report_is_an_accept(py_mirror) -> None:
    verdict = check(FakeSandbox(writes(all_passed())), py_mirror)
    assert verdict.verdict == "accept", verdict.reason


def test_the_command_writes_to_a_per_run_report_path_not_the_task_path(py_mirror) -> None:
    fake = FakeSandbox(writes(all_passed()))
    check(fake, py_mirror)
    command = fake.requests[0].command
    assert "/logs/verifier/junit.xml" not in command
    assert "--junitxml=/logs/verifier/report-" in command


def test_isolated_flag_false_can_never_accept(py_mirror) -> None:
    fake = FakeSandbox(writes(all_passed()))
    fake.isolated = False
    verdict = check(fake, py_mirror)
    assert verdict.verdict == "error_infra"
    assert verdict.verdict != "accept"


def test_missing_f2p_id_in_the_report_is_a_reject(py_mirror) -> None:
    """T29: a report that lacks an expected F2P id counts as a failure."""
    cases = all_passed()
    del cases[dotted(F2P[0])]
    verdict = check(FakeSandbox(writes(cases)), py_mirror)
    assert verdict.verdict == "reject"
    assert verdict.category == "hidden_checks_failed"
    assert verdict.hard["missing_ids"] == 1  # type: ignore[index]


@pytest.mark.parametrize("status", ["skipped", "failed", "error"])
def test_a_non_passed_expected_id_is_a_reject(py_mirror, status) -> None:
    cases = all_passed()
    cases[dotted(P2P[0])] = status
    verdict = check(FakeSandbox(writes(cases)), py_mirror)
    assert verdict.verdict == "reject"
    # The failing id is a visible one: the generator may see its id and status.
    assert verdict.feedback_items[0]["type"] == "visible_test"


def test_an_unexpected_failing_test_is_a_reject(py_mirror) -> None:
    cases = {**all_passed(), "tests.test_other::test_new": "failed"}
    verdict = check(FakeSandbox(writes(cases)), py_mirror)
    assert verdict.verdict == "reject"


def test_a_non_zero_exit_code_is_a_reject_even_with_a_green_report(py_mirror) -> None:
    verdict = check(FakeSandbox(writes(all_passed(), exit_code=1)), py_mirror)
    assert verdict.verdict == "reject"


def test_no_report_is_a_reject_not_an_accept(py_mirror) -> None:
    verdict = check(FakeSandbox(lambda request: RunResult(exit_code=0)), py_mirror)
    assert verdict.verdict == "reject"
    assert verdict.category == "junit_missing"


def test_a_symlinked_report_is_not_followed(py_mirror, tmp_path) -> None:
    target = tmp_path / "host-secret.xml"
    target.write_text(junit_xml(all_passed()), encoding="utf-8")

    def behavior(request: RunRequest) -> RunResult:
        report_path(request).symlink_to(target)
        return RunResult(exit_code=0)

    verdict = check(FakeSandbox(behavior), py_mirror)
    assert verdict.verdict == "reject"
    assert verdict.category == "junit_invalid"


@pytest.mark.parametrize(
    "content",
    [
        '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><testsuites>&a;</testsuites>',
        "not xml at all",
        junit_xml({"tests.test_calc::test_a": "passed"}).replace("</testsuite>", "")
        + "<testsuite><testcase classname='tests.test_calc' name='test_a'/></testsuite>",
    ],
    ids=["dtd", "garbage", "truncated-with-duplicate"],
)
def test_hostile_reports_are_rejects_not_infra_errors(py_mirror, content) -> None:
    """A diff must not be able to turn the run into a free retry (error_infra)."""
    verdict = check(FakeSandbox(writes(content)), py_mirror)
    assert verdict.verdict == "reject"
    assert verdict.category == "junit_invalid"


def test_a_file_at_the_task_junit_path_is_a_forgery(py_mirror) -> None:
    def behavior(request: RunRequest) -> RunResult:
        report_path(request).write_text(junit_xml(all_passed()), encoding="utf-8")
        (request.logs_dir / "junit.xml").write_text(junit_xml(all_passed()), encoding="utf-8")
        return RunResult(exit_code=0)

    verdict = check(FakeSandbox(behavior), py_mirror)
    assert verdict.verdict == "cheat_suspected"
    assert verdict.category == "junit_forged"


def test_timeout_is_a_reject_attributable_to_the_diff(py_mirror) -> None:
    fake = FakeSandbox(lambda request: RunResult(exit_code=None, timed_out=True))
    verdict = check(fake, py_mirror)
    assert (verdict.verdict, verdict.category) == ("reject", "timeout")


def test_oom_is_a_reject_attributable_to_the_diff(py_mirror) -> None:
    fake = FakeSandbox(lambda request: RunResult(exit_code=137, oom_killed=True))
    verdict = check(fake, py_mirror)
    assert (verdict.verdict, verdict.category) == ("reject", "oom")


def test_sandbox_failure_is_error_infra(py_mirror) -> None:
    def behavior(request: RunRequest) -> RunResult:
        raise SandboxError("daemon is down")

    verdict = check(FakeSandbox(behavior), py_mirror)
    assert verdict.verdict == "error_infra"
    assert verdict.feedback is None


def test_unexpected_exception_is_error_infra(py_mirror) -> None:
    def behavior(request: RunRequest) -> RunResult:
        raise RuntimeError("bug")

    verdict = check(FakeSandbox(behavior), py_mirror)
    assert verdict.verdict == "error_infra"


def test_missing_docker_binary_is_error_infra(py_mirror, monkeypatch) -> None:
    original = sandbox_module.subprocess.run
    docker_calls: list[object] = []

    def no_docker(command: list[str], *args: object, **kwargs: object):
        if command[0] == "docker":
            docker_calls.append(command)
            raise FileNotFoundError("docker")
        return original(command, *args, **kwargs)

    monkeypatch.setattr(sandbox_module.subprocess, "run", no_docker)
    real = DockerSandbox(image="sha256:" + "b" * 64)
    verdict = check(real, py_mirror)
    assert docker_calls, "the verifier never reached docker"
    assert verdict.verdict == "error_infra"
    assert "docker is not usable" in verdict.reason


def test_a_tag_only_image_is_refused() -> None:
    with pytest.raises(ValueError):
        DockerSandbox(image="python:3.12-slim")


def test_missing_mirror_is_error_infra(tmp_path) -> None:
    verdict = verify(
        TASKS / ROUND,
        ROUND,
        GOLD,
        tmp_path / "nope",
        run=None,
        sandbox=FakeSandbox(writes(all_passed())),
        attempt=1,
        base_commit="1" * 40,
    )
    assert verdict.verdict == "error_infra"


def test_unknown_commit_is_error_infra(py_mirror) -> None:
    verdict = check(FakeSandbox(writes(all_passed())), py_mirror)
    assert verdict.verdict == "accept"
    other = verify(
        TASKS / ROUND,
        ROUND,
        GOLD,
        py_mirror[0],
        run=None,
        sandbox=FakeSandbox(writes(all_passed())),
        attempt=1,
        base_commit="1" * 40,
    )
    assert other.verdict == "error_infra"


@pytest.mark.parametrize("task_id", ["no-such-task", "../escape", "UPPER"])
def test_unknown_or_malicious_task_id_is_error_infra(py_mirror, task_id) -> None:
    verdict = verify(
        TASKS / ROUND,
        task_id,
        GOLD,
        py_mirror[0],
        run=None,
        sandbox=FakeSandbox(writes(all_passed())),
        attempt=1,
        base_commit=py_mirror[1],
    )
    assert verdict.verdict == "error_infra"


def test_task_with_empty_f2p_is_error_infra(py_mirror, tmp_path) -> None:
    store = copy_store(ROUND, tmp_path / "store")
    (store / "hidden" / ROUND / "f2p.json").write_text("[]", encoding="utf-8")
    verdict = check(FakeSandbox(writes(all_passed())), py_mirror, store=store)
    assert verdict.verdict == "error_infra"


def test_test_command_without_the_junit_path_is_error_infra(py_mirror, tmp_path) -> None:
    store = copy_store(ROUND, tmp_path / "store")
    edit_verifier(store, ROUND, test_command="python -m pytest -q tests/test_calc.py")
    verdict = check(FakeSandbox(writes(all_passed())), py_mirror, store=store)
    assert verdict.verdict == "error_infra"


def test_garbage_diff_is_patch_invalid(py_mirror) -> None:
    verdict = check(FakeSandbox(writes(all_passed())), py_mirror, diff=b"this is not a patch\n")
    assert (verdict.verdict, verdict.category) == ("reject", "patch_invalid")
    assert verdict.feedback == {"items": [{"type": "patch_invalid"}]}


def test_diff_that_does_not_apply_is_patch_invalid(py_mirror) -> None:
    diff = GOLD.replace(b"return round(x, ndigits)", b"return something_else(x)")
    verdict = check(FakeSandbox(writes(all_passed())), py_mirror, diff=diff)
    assert (verdict.verdict, verdict.category) == ("reject", "patch_invalid")


def big_diff(lines: int) -> bytes:
    body = "".join(f"+x{i} = {i}\n" for i in range(lines))
    return (
        f"diff --git a/src/calc/big.py b/src/calc/big.py\nnew file mode 100644\n"
        f"--- /dev/null\n+++ b/src/calc/big.py\n@@ -0,0 +1,{lines} @@\n{body}"
    ).encode()


def test_patch_size_cap_is_three_times_the_class_cap(py_mirror) -> None:
    fake = FakeSandbox(writes(all_passed()))
    over = check(fake, py_mirror, diff=big_diff(601))
    assert (over.verdict, over.category) == ("reject", "patch_invalid")
    assert "601" in over.reason
    at_cap = check(fake, py_mirror, diff=big_diff(600))
    assert at_cap.category != "patch_invalid"


def test_run_exit_values_cannot_buy_an_accept(py_mirror) -> None:
    run = {"exit": "abort_spec_conflict", "cost": {"source": "gateway", "usd_real": 1.0}}
    verdict = check(FakeSandbox(writes(all_passed())), py_mirror, run=run)
    assert (verdict.verdict, verdict.category) == ("reject", "abort_spec_conflict")
    garbage = check(FakeSandbox(writes(all_passed())), py_mirror, run={"exit": "banana"})
    assert garbage.verdict == "error_infra"


def test_cost_check_spares_local_arms_with_shadow_cost(py_mirror) -> None:
    run = {
        "exit": "done",
        "tokens": {"input": 50000, "output": 2000},
        "cost": {"usd_real": 0.0, "usd_shadow": 0.4, "source": "gateway"},
    }
    verdict = check(FakeSandbox(writes(all_passed())), py_mirror, run=run)
    assert verdict.verdict == "accept"


def test_every_verdict_validates_against_the_schema(py_mirror) -> None:
    for behavior in (
        writes(all_passed()),
        lambda request: RunResult(exit_code=None, timed_out=True),
        lambda request: RunResult(exit_code=0),
    ):
        validate_document(check(FakeSandbox(behavior), py_mirror).to_dict())
