"""The matrix runner: planning, idempotency, key lifecycle, layout and gate."""

from __future__ import annotations

import json
import os
import re
import shutil
import tomllib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from factory.adapters.output import validate_run_document
from factory.metrics.load import load_dataset
from factory.run_matrix import (
    REPO_ROOT,
    Deps,
    ExistingVerdict,
    PlannedRun,
    build_input_document,
    build_plan,
    load_matrix,
    main,
    next_attempt,
    run_id_for,
    scan_verdicts,
)

from .support import (
    FIXTURES,
    KEY,
    TASK_ID,
    FakeDocker,
    FakeHarbor,
    FakeKeys,
    FakeVerifier,
    add_git_snapshot,
    arm,
    write_arms,
    write_manifest,
    write_run_doc,
    write_store,
    write_verdict_doc,
)


class RecordingToHarbor:
    """Records conversions instead of writing a real Harbor task."""

    def __init__(self) -> None:
        self.calls: list[tuple[Path, Path, dict[str, object]]] = []

    def __call__(self, visible_task_dir: Path, out_dir: Path, **kwargs: object) -> Path:
        self.calls.append((Path(visible_task_dir), Path(out_dir), kwargs))
        target = Path(out_dir) / Path(visible_task_dir).name
        target.mkdir(parents=True, exist_ok=True)
        return target


def _deps(
    *,
    keys: FakeKeys | None = None,
    harbor: FakeHarbor | None = None,
    verifier: FakeVerifier | None = None,
    docker: FakeDocker | None = None,
) -> Deps:
    return Deps(
        key_client=keys or FakeKeys(),
        harbor=harbor or FakeHarbor(),
        verifier=verifier or FakeVerifier(),
        docker=docker or FakeDocker(),
    )


def _manifest(store: Path) -> Path:
    path = store.parent / "public-v1.manifest.json"
    if not path.exists():
        write_manifest(path, sorted(task.name for task in (store / "hidden").iterdir()))
    return path


def _run_args(store: Path, arms: Path, out: Path, work: Path, *extra: str) -> list[str]:
    return [
        "run",
        "--store",
        str(store),
        "--arms",
        str(arms),
        "--out",
        str(out),
        "--work",
        str(work),
        "--manifest",
        str(_manifest(store)),
        "--gateway-url",
        "http://gateway:4000/v1",
        *extra,
    ]


# ---------------------------------------------------------------------------
# Arms, tasks and planning
# ---------------------------------------------------------------------------


def test_input_document_points_the_abort_channel_at_the_task_workdir(tmp_path: Path) -> None:
    store = write_store(tmp_path)
    task_path = store / "visible" / TASK_ID / "factory.task.json"
    task = json.loads(task_path.read_text(encoding="utf-8"))
    task["repo"]["workdir"] = "/testbed"
    task_path.write_text(json.dumps(task), encoding="utf-8")
    matrix = load_matrix(write_arms(tmp_path / "arms.json"))
    run = PlannedRun(
        arm=matrix.arms[0], task_id=TASK_ID, repetition=1, attempt=1, run_id="r-0000001"
    )

    document = build_input_document(run, store, task)

    assert document["abort_path"] == "/testbed/.factory/abort.json"


def test_repository_arms_file_has_the_six_f1_arms() -> None:
    matrix = load_matrix(REPO_ROOT / "matrix" / "arms-v1.json")

    assert [arm.id for arm in matrix.arms] == ["A1", "A2", "A3", "A4", "A5", "A6"]
    assert matrix.max_parallel == 3
    assert matrix.providers == {"anthropic": 3, "zai": 5, "local": 2}
    assert {arm.id: arm.k for arm in matrix.arms} == {
        "A1": 3,
        "A2": 5,
        "A3": 5,
        "A4": 5,
        "A5": 5,
        "A6": 5,
    }
    for entry in matrix.arms:
        assert entry.budget["usd"] == 2.0
        assert entry.budget["wall_s"] == 1800
        assert entry.data_class == "public"
        assert entry.billing == "plan"
    assert matrix.arms[0].budget["max_turns"] == 60
    expected_limits = {
        "A1": {"context": 200000, "output": 32768},
        "A2": {"context": 200000, "output": 32768},
        "A3": {"context": 200000, "output": 32768},
        "A4": {"context": 32768, "output": 8192},
        "A5": {"context": 32768, "output": 8192},
        "A6": {"context": 200000, "output": 32768},
    }
    assert {entry.id: dict(entry.model_limits) for entry in matrix.arms} == expected_limits


def test_arms_file_requires_billing_and_model_limits(tmp_path: Path) -> None:
    document = json.loads((REPO_ROOT / "matrix" / "arms-v1.json").read_text(encoding="utf-8"))
    path = tmp_path / "arms.json"

    for field in ("billing", "model_limits"):
        broken = json.loads(json.dumps(document))
        del broken["arms"][0][field]
        path.write_text(json.dumps(broken), encoding="utf-8")
        with pytest.raises((TypeError, ValueError), match=field):
            load_matrix(path)

    broken = json.loads(json.dumps(document))
    broken["arms"][0]["billing"] = "free"
    path.write_text(json.dumps(broken), encoding="utf-8")
    with pytest.raises(ValueError, match="billing"):
        load_matrix(path)

    for limits in (
        {"context": 0, "output": 32768},
        {"context": 200000},
        {"context": 200000, "output": 32768, "extra": 1},
        {"context": True, "output": 32768},
    ):
        broken = json.loads(json.dumps(document))
        broken["arms"][0]["model_limits"] = limits
        path.write_text(json.dumps(broken), encoding="utf-8")
        with pytest.raises(ValueError, match="model_limits"):
            load_matrix(path)


def test_plan_is_arms_times_tasks_times_k(tmp_path: Path) -> None:
    path = write_arms(
        tmp_path / "arms.json",
        [arm("A1", k=2), arm("A3", executor="opencode", k=3, provider="zai")],
    )
    matrix = load_matrix(path)

    plan = build_plan(matrix.arms, ["t1", "t2"], None, {})

    assert len(plan) == 10
    assert plan[0].run_id == "a1-t1-r1-a1"
    assert plan[-1].run_id == "a3-t2-r3-a1"
    assert len(build_plan(matrix.arms, ["t1", "t2"], 1, {})) == 4


def test_dry_run_output_with_capsys(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = write_store(tmp_path)
    arms = write_arms(
        tmp_path / "arms.json",
        [arm("A1", k=1), arm("A3", executor="opencode", k=1, provider="zai")],
    )
    out = tmp_path / "out"
    work = tmp_path / "work"

    code = main(
        _run_args(
            store,
            arms,
            out,
            work,
            "--arm",
            "A1",
            "--task",
            TASK_ID,
            "--k",
            "2",
            "--dry-run",
        ),
        deps=_deps(),
    )

    lines = capsys.readouterr().out.splitlines()
    assert code == 0
    assert not work.exists()
    assert lines[0] == "a1-demo-task-r1-a1"
    assert lines[2] == "a1-demo-task-r2-a1"
    assert "--job-name" in lines[1]
    assert "--model anthropic/claude-sonnet-5-5" in lines[1]


def test_unknown_arm_or_task_is_rejected(tmp_path: Path) -> None:
    store = write_store(tmp_path)
    arms = write_arms(tmp_path / "arms.json")

    with pytest.raises(ValueError, match="unknown arm"):
        main(_run_args(store, arms, tmp_path / "out", tmp_path / "work", "--arm", "A9"))
    with pytest.raises(ValueError, match="unknown task"):
        main(_run_args(store, arms, tmp_path / "out", tmp_path / "work", "--task", "nope"))


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_idempotency_skips_done_and_retries_infra(tmp_path: Path) -> None:
    path = write_arms(tmp_path / "arms.json")
    arms = load_matrix(path).arms

    done = {("A1", "t1", 1): [ExistingVerdict(1, "accept")]}
    assert build_plan(arms, ["t1"], None, done) == []

    infra = {("A1", "t1", 1): [ExistingVerdict(1, "error_infra")]}
    retried = build_plan(arms, ["t1"], None, infra)
    assert [(run.attempt, run.run_id) for run in retried] == [(2, "a1-t1-r1-a2")]

    exhausted = {
        ("A1", "t1", 1): [
            ExistingVerdict(1, "error_infra"),
            ExistingVerdict(2, "error_infra"),
            ExistingVerdict(3, "error_infra"),
        ]
    }
    assert build_plan(arms, ["t1"], None, exhausted) == []


def test_scan_verdicts_groups_by_cell(tmp_path: Path) -> None:
    root = tmp_path / "out"
    write_verdict_doc(root, "a1-demo-task-r1-a1", attempt=1, verdict="error_infra")
    write_verdict_doc(root, "a1-demo-task-r1-a2", attempt=2, verdict="reject")

    grouped = scan_verdicts(root / "verdicts")

    assert next_attempt(grouped, "A1", TASK_ID, 1) is None
    write_verdict_doc(root, "a1-demo-task-r1-a3", attempt=3, verdict="error_infra")
    grouped = scan_verdicts(root / "verdicts")
    assert next_attempt(grouped, "A1", TASK_ID, 1) is None


def _write_small_arms() -> Path:
    import tempfile

    path = Path(tempfile.mkdtemp()) / "arms.json"
    return write_arms(path)


# ---------------------------------------------------------------------------
# Key lifecycle and layout
# ---------------------------------------------------------------------------


def test_one_run_writes_the_dataset_layout(tmp_path: Path) -> None:
    store = write_store(tmp_path)
    arms = write_arms(tmp_path / "arms.json", [arm("A1", k=1)], max_parallel=1)
    out = tmp_path / "out"
    work = tmp_path / "work"
    keys = FakeKeys()
    harbor = FakeHarbor()
    verifier = FakeVerifier("reject")

    code = main(
        _run_args(store, arms, out, work), deps=_deps(keys=keys, harbor=harbor, verifier=verifier)
    )

    run_id = "a1-demo-task-r1-a1"
    assert code == 0
    assert keys.mints == [("public", 2.0, 2400, run_id)]
    assert keys.spends == [KEY]
    assert keys.revoked == [KEY]
    assert harbor.environments[0]["ANTHROPIC_API_KEY"] == KEY
    assert harbor.environments[0]["ANTHROPIC_BASE_URL"] == "http://gateway:4000"

    run_document = json.loads((out / "runs" / f"{run_id}.json").read_text())
    assert run_document["run_id"] == run_id
    assert run_document["exit"] == "done"
    assert run_document["tokens"]["input"] == 100
    assert run_document["tokens"]["output"] == 20
    assert run_document["cost"]["usd_real"] == 0.0
    assert run_document["cost"]["usd_shadow"] == 0.25
    assert run_document["provenance"]["model_resolved"] == "anthropic/claude-sonnet-5-5"
    assert run_document["diff"]["files_changed"] == 1
    assert run_document["diff"]["lines_added"] == 1
    assert run_document["diff"]["lines_removed"] == 1
    assert (out / "runs" / f"{run_id}.diff").read_bytes() == (
        Path(__file__).parent / "fixtures" / "harbor_trial" / "verifier" / "diff.patch"
    ).read_bytes()

    verdict = json.loads((out / "verdicts" / f"{run_id}.json").read_text())
    assert verdict["verdict"] == "reject"
    assert verdict["arm"] == "A1"
    assert verdict["repetition"] == 1
    assert verdict["attempt"] == 1

    dataset = load_dataset(out)
    assert len(dataset.records) == 1
    assert dataset.records[0].run_id == run_id
    assert dataset.records[0].verdict == "reject"
    assert dataset.records[0].cost_usd == 0.25
    assert dataset.records[0].diff_text


def test_stale_job_dir_is_quarantined_before_harbor_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = write_store(tmp_path)
    arms = write_arms(tmp_path / "arms.json", [arm("A1", k=1)], max_parallel=1)
    out = tmp_path / "out"
    work = tmp_path / "work"
    run_id = "a1-demo-task-r1-a1"
    old_result = work / "jobs" / run_id / "trial__old" / "result.json"
    old_result.parent.mkdir(parents=True)
    old_result.write_text('{"agent_timeout_error": "stale"}', encoding="utf-8")
    harbor = FakeHarbor()
    deps = Deps(
        key_client=FakeKeys(),
        harbor=harbor,
        verifier=FakeVerifier(),
        docker=FakeDocker(),
        clock=lambda: datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC),
    )

    code = main(_run_args(store, arms, out, work), deps=deps)

    assert code == 0
    assert harbor.job_dir_entries == [[]]
    stale = work / "jobs" / f"{run_id}.stale-20260304T050607Z"
    assert (stale / "trial__old" / "result.json").read_text() == '{"agent_timeout_error": "stale"}'
    assert sorted(path.name for path in (work / "jobs" / run_id).iterdir()) == ["trial__fake"]
    assert f"{run_id}: previous job dir moved to {stale}" in capsys.readouterr().err


def test_absent_job_dir_is_not_quarantined(tmp_path: Path) -> None:
    store = write_store(tmp_path)
    arms = write_arms(tmp_path / "arms.json", [arm("A1", k=1)], max_parallel=1)
    out = tmp_path / "out"
    work = tmp_path / "work"

    code = main(_run_args(store, arms, out, work), deps=_deps())

    assert code == 0
    assert not list((work / "jobs").glob("*.stale-*"))


def test_cost_goes_to_shadow_for_plan_arms_and_real_for_api_arms(tmp_path: Path) -> None:
    store = write_store(tmp_path)
    arms = write_arms(
        tmp_path / "arms.json",
        [arm("A1", billing="plan"), arm("A2", billing="api")],
        max_parallel=1,
    )
    out = tmp_path / "out"

    code = main(_run_args(store, arms, out, tmp_path / "work"), deps=_deps())

    assert code == 0
    plan = json.loads((out / "runs" / "a1-demo-task-r1-a1.json").read_text())
    api = json.loads((out / "runs" / "a2-demo-task-r1-a1.json").read_text())
    assert plan["cost"]["usd_real"] == 0.0
    assert plan["cost"]["usd_shadow"] == 0.25
    assert api["cost"]["usd_real"] == 0.25
    assert api["cost"]["usd_shadow"] == 0.0


def test_harbor_runs_with_the_pinned_agents_on_pythonpath(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTHONPATH", "/existing/site-packages")
    store = write_store(tmp_path)
    arms = write_arms(tmp_path / "arms.json", [arm("A1", k=1)], max_parallel=1)
    harbor = FakeHarbor()

    code = main(
        _run_args(store, arms, tmp_path / "out", tmp_path / "work"),
        deps=_deps(harbor=harbor),
    )

    assert code == 0
    pythonpath = harbor.environments[0]["PYTHONPATH"]
    assert pythonpath == os.pathsep.join(
        (str(REPO_ROOT / "infra" / "harbor"), "/existing/site-packages")
    )


def test_key_is_revoked_when_harbor_raises(tmp_path: Path) -> None:
    store = write_store(tmp_path)
    arms = write_arms(tmp_path / "arms.json", [arm("A1", k=1)], max_parallel=1)
    out = tmp_path / "out"
    keys = FakeKeys()
    verifier = FakeVerifier()

    code = main(
        _run_args(store, arms, out, tmp_path / "work"),
        deps=_deps(keys=keys, harbor=FakeHarbor(fail=True), verifier=verifier),
    )

    assert code == 0
    assert keys.revoked == [KEY]
    assert verifier.calls == []
    run_id = "a1-demo-task-r1-a1"
    run_document = json.loads((out / "runs" / f"{run_id}.json").read_text())
    assert run_document["exit"] == "error"
    assert "harbor exploded" in run_document["exit_detail"]
    verdict = json.loads((out / "verdicts" / f"{run_id}.json").read_text())
    assert verdict["verdict"] == "error_infra"
    assert "harbor exploded" in verdict["reason"]


def test_harbor_crash_without_a_trial_yields_error_infra(tmp_path: Path) -> None:
    store = write_store(tmp_path)
    arms = write_arms(tmp_path / "arms.json", [arm("A1", k=1)], max_parallel=1)
    out = tmp_path / "out"
    verifier = FakeVerifier()

    code = main(
        _run_args(store, arms, out, tmp_path / "work"),
        deps=_deps(harbor=FakeHarbor(trial_source=None), verifier=verifier),
    )

    run_id = "a1-demo-task-r1-a1"
    assert code == 0
    assert verifier.calls == []
    run_document = json.loads((out / "runs" / f"{run_id}.json").read_text())
    assert run_document["exit"] == "error"
    verdict = json.loads((out / "verdicts" / f"{run_id}.json").read_text())
    assert verdict["verdict"] == "error_infra"


def test_setup_exception_is_error_infra_and_retried(tmp_path: Path) -> None:
    store = write_store(tmp_path)
    arms = write_arms(tmp_path / "arms.json", [arm("A1", k=1)], max_parallel=1)
    out = tmp_path / "out"
    work = tmp_path / "work"
    harbor = FakeHarbor(trial_source=FIXTURES / "harbor_setup_failure")
    verifier = FakeVerifier()

    code = main(_run_args(store, arms, out, work), deps=_deps(harbor=harbor, verifier=verifier))

    run_id = "a1-demo-task-r1-a1"
    assert code == 0
    assert verifier.calls == []
    run_document = json.loads((out / "runs" / f"{run_id}.json").read_text())
    assert run_document["exit"] == "error"
    fixture = json.loads((FIXTURES / "harbor_setup_failure" / "result.json").read_text())
    message = fixture["exception_info"]["exception_message"]
    expected = f"NetworkConnectionError: {message[:300]}"
    assert run_document["exit_detail"] == expected
    verdict = json.loads((out / "verdicts" / f"{run_id}.json").read_text())
    assert verdict["verdict"] == "error_infra"
    assert verdict["reason"] == expected

    code = main(_run_args(store, arms, out, work), deps=_deps(harbor=harbor))

    assert code == 0
    assert harbor.calls == 2
    retried = json.loads((out / "verdicts" / "a1-demo-task-r1-a2.json").read_text())
    assert retried["attempt"] == 2
    assert retried["verdict"] == "error_infra"


def test_provider_rate_limit_after_start_is_error_infra(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = write_store(tmp_path)
    arms = write_arms(tmp_path / "arms.json", [arm("A1", k=1)], max_parallel=1)
    out = tmp_path / "out"
    harbor = FakeHarbor(trial_source=FIXTURES / "harbor_rate_limit")
    verifier = FakeVerifier()

    code = main(
        _run_args(store, arms, out, tmp_path / "work"),
        deps=_deps(harbor=harbor, verifier=verifier),
    )

    run_id = "a1-demo-task-r1-a1"
    assert code == 1
    assert verifier.calls == []
    run_document = json.loads((out / "runs" / f"{run_id}.json").read_text())
    validate_run_document(run_document)
    assert run_document["exit"] == "error"
    fixture = json.loads((FIXTURES / "harbor_rate_limit" / "result.json").read_text())
    message = fixture["exception_info"]["exception_message"]
    expected = f"ApiRateLimitError: {message[:300]}"
    assert run_document["exit_detail"] == expected
    verdict = json.loads((out / "verdicts" / f"{run_id}.json").read_text())
    assert verdict["verdict"] == "error_infra"
    assert verdict["reason"] == expected
    assert f"provider rate limit: {expected}" in capsys.readouterr().err


def test_provider_rate_limit_stops_the_matrix(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = write_store(tmp_path)
    arms = write_arms(tmp_path / "arms.json", [arm("A1", k=3)], max_parallel=1)
    out = tmp_path / "out"
    harbor = FakeHarbor(trial_source=FIXTURES / "harbor_rate_limit")

    code = main(
        _run_args(store, arms, out, tmp_path / "work"),
        deps=_deps(harbor=harbor),
    )

    assert code == 1
    assert harbor.calls == 1
    captured = capsys.readouterr()
    assert "provider rate limit: ApiRateLimitError: [1308] Usage limit reached" in captured.err
    assert "stopped: 2 runs not started" in captured.err
    assert len(list((out / "verdicts").glob("*.json"))) == 1


def test_provider_rate_limit_lets_in_flight_runs_finish(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = write_store(tmp_path)
    arms = write_arms(tmp_path / "arms.json", [arm("A1", k=3)], max_parallel=2)
    out = tmp_path / "out"
    harbor = FakeHarbor(trial_source=FIXTURES / "harbor_rate_limit", delay=0.1)

    code = main(
        _run_args(store, arms, out, tmp_path / "work"),
        deps=_deps(harbor=harbor),
    )

    assert code == 1
    assert harbor.calls == 2
    verdicts = [json.loads(path.read_text()) for path in (out / "verdicts").glob("*.json")]
    assert [verdict["verdict"] for verdict in verdicts] == ["error_infra", "error_infra"]
    assert "stopped: 1 runs not started" in capsys.readouterr().err


def test_agent_timeout_after_execution_keeps_map_exit(tmp_path: Path) -> None:
    store = write_store(tmp_path)
    arms = write_arms(tmp_path / "arms.json", [arm("A1", k=1)], max_parallel=1)
    out = tmp_path / "out"
    harbor = FakeHarbor(trial_source=FIXTURES / "harbor_agent_timeout")
    verifier = FakeVerifier("reject")

    code = main(
        _run_args(store, arms, out, tmp_path / "work"),
        deps=_deps(harbor=harbor, verifier=verifier),
    )

    run_id = "a1-demo-task-r1-a1"
    assert code == 0
    assert len(verifier.calls) == 1
    run_document = json.loads((out / "runs" / f"{run_id}.json").read_text())
    assert run_document["exit"] == "budget_exceeded"
    verdict = json.loads((out / "verdicts" / f"{run_id}.json").read_text())
    assert verdict["verdict"] == "reject"


def test_abort_channel_is_honored_without_calling_the_verifier(tmp_path: Path) -> None:
    store = write_store(tmp_path)
    arms = write_arms(tmp_path / "arms.json", [arm("A1", k=1)], max_parallel=1)
    out = tmp_path / "out"
    trial = tmp_path / "abort-trial"
    shutil.copytree(FIXTURES / "harbor_trial", trial)
    (trial / "verifier" / "diff.patch").write_bytes(
        b"diff --git a/.factory/abort.json b/.factory/abort.json\n"
        b"new file mode 100644\n"
        b"index 0000000..1111111\n"
        b"--- /dev/null\n"
        b"+++ b/.factory/abort.json\n"
        b"@@ -0,0 +1 @@\n"
        b'+{"reason": "spec and tests disagree"}\n'
        b"diff --git a/src/calc.py b/src/calc.py\n"
        b"index 1111111..2222222 100644\n"
        b"--- a/src/calc.py\n"
        b"+++ b/src/calc.py\n"
        b"@@ -1,2 +1,2 @@\n"
        b"-old\n"
        b"+new\n"
        b" keep\n"
    )
    verifier = FakeVerifier()

    code = main(
        _run_args(store, arms, out, tmp_path / "work"),
        deps=_deps(harbor=FakeHarbor(trial_source=trial), verifier=verifier),
    )

    run_id = "a1-demo-task-r1-a1"
    assert code == 0
    assert verifier.calls == []
    run_document = json.loads((out / "runs" / f"{run_id}.json").read_text())
    assert run_document["exit"] == "abort_spec_conflict"
    assert run_document["abort"] == {"reason": "spec and tests disagree"}
    run_diff = (out / "runs" / f"{run_id}.diff").read_bytes()
    assert b".factory/" not in run_diff
    assert b"src/calc.py" in run_diff
    assert b"+new\n" in run_diff
    verdict = json.loads((out / "verdicts" / f"{run_id}.json").read_text())
    assert verdict["verdict"] == "reject"
    assert verdict["category"] == "abort_spec_conflict"


def test_verifier_that_writes_nothing_becomes_error_infra(tmp_path: Path) -> None:
    store = write_store(tmp_path)
    arms = write_arms(tmp_path / "arms.json", [arm("A1", k=1)], max_parallel=1)
    out = tmp_path / "out"

    code = main(
        _run_args(store, arms, out, tmp_path / "work"),
        deps=_deps(verifier=FakeVerifier(write=False)),
    )

    run_id = "a1-demo-task-r1-a1"
    assert code == 0
    run_document = json.loads((out / "runs" / f"{run_id}.json").read_text())
    assert run_document["exit"] == "done"
    verdict = json.loads((out / "verdicts" / f"{run_id}.json").read_text())
    assert verdict["verdict"] == "error_infra"
    assert "no verdict" in verdict["reason"]


# ---------------------------------------------------------------------------
# Task image availability
# ---------------------------------------------------------------------------


def _task_image(store: Path) -> str:
    task = json.loads((store / "visible" / TASK_ID / "factory.task.json").read_text())
    return task["image"]


def test_present_task_image_is_not_pulled(tmp_path: Path) -> None:
    store = write_store(tmp_path)
    arms = write_arms(tmp_path / "arms.json", [arm("A1", k=1)], max_parallel=1)
    docker = FakeDocker(present=True)
    verifier = FakeVerifier()

    code = main(
        _run_args(store, arms, tmp_path / "out", tmp_path / "work"),
        deps=_deps(docker=docker, verifier=verifier),
    )

    assert code == 0
    assert docker.inspects == [_task_image(store)]
    assert docker.pulls == []
    assert len(verifier.calls) == 1


def test_missing_task_image_is_pulled_once_before_verifying(tmp_path: Path) -> None:
    store = write_store(tmp_path)
    arms = write_arms(tmp_path / "arms.json", [arm("A1", k=1)], max_parallel=1)
    events: list[str] = []
    docker = FakeDocker(present=False, events=events)
    verifier = FakeVerifier(events=events)

    code = main(
        _run_args(store, arms, tmp_path / "out", tmp_path / "work"),
        deps=_deps(docker=docker, verifier=verifier),
    )

    assert code == 0
    assert docker.pulls == [_task_image(store)]
    assert events == ["inspect", "pull", "verify"]


def test_parallel_runs_of_one_task_pull_the_image_once(tmp_path: Path) -> None:
    store = write_store(tmp_path)
    arms = write_arms(tmp_path / "arms.json", [arm("A1", k=2)], max_parallel=2)
    docker = FakeDocker(present=False, pull_delay=0.05)
    verifier = FakeVerifier()

    code = main(
        _run_args(store, arms, tmp_path / "out", tmp_path / "work"),
        deps=_deps(docker=docker, harbor=FakeHarbor(delay=0.02), verifier=verifier),
    )

    assert code == 0
    assert docker.pulls == [_task_image(store)]
    assert len(verifier.calls) == 2


def test_failed_pull_is_error_infra_and_retried(tmp_path: Path) -> None:
    store = write_store(tmp_path)
    arms = write_arms(tmp_path / "arms.json", [arm("A1", k=1)], max_parallel=1)
    out = tmp_path / "out"
    work = tmp_path / "work"
    verifier = FakeVerifier()

    code = main(
        _run_args(store, arms, out, work),
        deps=_deps(docker=FakeDocker(present=False, fail_pull=True), verifier=verifier),
    )

    assert code == 0
    assert verifier.calls == []
    verdict = json.loads((out / "verdicts" / "a1-demo-task-r1-a1.json").read_text())
    assert verdict["verdict"] == "error_infra"
    assert "docker pull" in verdict["reason"]
    assert "pull access denied" in verdict["reason"]

    retried_verifier = FakeVerifier()
    code = main(
        _run_args(store, arms, out, work),
        deps=_deps(docker=FakeDocker(present=False), verifier=retried_verifier),
    )

    assert code == 0
    assert retried_verifier.calls
    retried = json.loads((out / "verdicts" / "a1-demo-task-r1-a2.json").read_text())
    assert retried["attempt"] == 2
    assert retried["verdict"] == "reject"


def test_no_key_value_is_written_or_printed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = write_store(tmp_path)
    arms = write_arms(tmp_path / "arms.json", [arm("A1", k=1)], max_parallel=1)
    out = tmp_path / "out"
    work = tmp_path / "work"
    secret = "sk-test-SECRET-123"
    keys = FakeKeys(key=secret)
    harbor = FakeHarbor()

    code = main(_run_args(store, arms, out, work), deps=_deps(keys=keys, harbor=harbor))

    assert code == 0
    assert secret in harbor.environments[0]["ANTHROPIC_API_KEY"]
    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err
    for root in (out, work, store):
        for path in root.rglob("*"):
            if path.is_file():
                assert secret not in path.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Gateway URL, conversion and verifier base commit
# ---------------------------------------------------------------------------


def _bare_run_args(store: Path, arms: Path, out: Path, work: Path, *extra: str) -> list[str]:
    return [
        "run",
        "--store",
        str(store),
        "--arms",
        str(arms),
        "--out",
        str(out),
        "--work",
        str(work),
        "--manifest",
        str(_manifest(store)),
        *extra,
    ]


def test_tasks_are_converted_once_per_executor_with_the_gateway_host(tmp_path: Path) -> None:
    store = write_store(tmp_path)
    arms = write_arms(
        tmp_path / "arms.json",
        [
            arm("A1", executor="claude-code"),
            arm("A3", executor="opencode", provider="zai"),
        ],
        max_parallel=1,
    )
    work = tmp_path / "work"
    converter = RecordingToHarbor()
    harbor = FakeHarbor()
    url = "http://gateway.example:4000/v1"

    code = main(
        _run_args(store, arms, tmp_path / "out", work, "--gateway-url", url),
        deps=Deps(
            key_client=FakeKeys(),
            harbor=harbor,
            verifier=FakeVerifier(),
            to_harbor=converter,
            docker=FakeDocker(),
        ),
    )

    assert code == 0
    assert sorted(
        (out_dir.parent.relative_to(work).as_posix(), kwargs["executor"], kwargs["allowed_hosts"])
        for _visible, out_dir, kwargs in converter.calls
    ) == [
        ("harbor/claude-code-t1800", "claude-code", ("gateway.example",)),
        ("harbor/opencode-t1800", "opencode", ("gateway.example",)),
    ]
    environments = harbor.environments
    assert any(
        env.get("ANTHROPIC_BASE_URL") == "http://gateway.example:4000" for env in environments
    )
    assert any(env.get("OPENAI_BASE_URL") == url for env in environments)


def test_arm_wall_clock_sets_the_harbor_agent_timeout(tmp_path: Path) -> None:
    store = write_store(tmp_path)
    arms = write_arms(
        tmp_path / "arms.json",
        [
            arm("A1", budget={"usd": 2.0, "wall_s": 900, "max_turns": 60}),
            arm("A6", budget={"usd": 2.0, "wall_s": 1800, "max_turns": 60}),
        ],
        max_parallel=2,
    )
    work = tmp_path / "work"
    harbor = FakeHarbor()

    code = main(_run_args(store, arms, tmp_path / "out", work), deps=_deps(harbor=harbor))

    assert code == 0
    timeouts = {}
    for wall_s in (900, 1800):
        task_dir = work / "harbor" / f"claude-code-t{wall_s}" / TASK_ID
        config = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
        timeouts[wall_s] = config["agent"]["timeout_sec"]
    assert timeouts == {900: 900, 1800: 1800}
    assert {
        argv[argv.index("--path") + 1]: argv[argv.index("--job-name") + 1] for argv in harbor.argvs
    } == {
        str(work / "harbor" / "claude-code-t900" / TASK_ID): "a1-demo-task-r1-a1",
        str(work / "harbor" / "claude-code-t1800" / TASK_ID): "a6-demo-task-r1-a1",
    }


def test_gateway_url_defaults_to_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FACTORY_GATEWAY_URL", "http://env.example:9000/v1")
    store = write_store(tmp_path)
    arms = write_arms(tmp_path / "arms.json", [arm("A1", k=1)], max_parallel=1)
    converter = RecordingToHarbor()

    code = main(
        _bare_run_args(store, arms, tmp_path / "out", tmp_path / "work"),
        deps=Deps(
            key_client=FakeKeys(),
            harbor=FakeHarbor(),
            verifier=FakeVerifier(),
            to_harbor=converter,
            docker=FakeDocker(),
        ),
    )

    assert code == 0
    assert converter.calls[0][2]["allowed_hosts"] == ("env.example",)


def test_run_without_a_gateway_url_fails_clearly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FACTORY_GATEWAY_URL", raising=False)
    store = write_store(tmp_path)
    arms = write_arms(tmp_path / "arms.json")

    code = main(_bare_run_args(store, arms, tmp_path / "out", tmp_path / "work"), deps=_deps())

    assert code == 2
    assert "gateway" in capsys.readouterr().err.lower()


def test_dry_run_does_not_require_a_gateway_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FACTORY_GATEWAY_URL", raising=False)
    store = write_store(tmp_path)
    arms = write_arms(tmp_path / "arms.json", [arm("A1", k=1)])

    code = main(
        _bare_run_args(store, arms, tmp_path / "out", tmp_path / "work", "--dry-run"),
        deps=_deps(),
    )

    assert code == 0


def test_verifier_gets_the_snapshot_head_as_base_commit(tmp_path: Path) -> None:
    store = write_store(tmp_path)
    commit = add_git_snapshot(store)
    arms = write_arms(tmp_path / "arms.json", [arm("A1", k=1)], max_parallel=1)
    verifier = FakeVerifier()

    code = main(
        _run_args(store, arms, tmp_path / "out", tmp_path / "work"),
        deps=_deps(verifier=verifier),
    )

    assert code == 0
    argv = verifier.calls[0]
    assert argv[argv.index("--base-commit") + 1] == commit


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


def test_concurrency_respects_the_provider_and_global_caps(tmp_path: Path) -> None:
    store = write_store(tmp_path)
    arms = write_arms(
        tmp_path / "arms.json",
        [
            arm("A2", "codex", "zai/glm-5.3", k=2, provider="zai"),
            arm("A3", "opencode", "zai/glm-5.3", k=2, provider="zai"),
            arm("A4", "opencode", "local/nanbeige4.3-33b", k=2, provider="local"),
            arm("A5", "mini-swe-agent", "local/nanbeige4.3-33b", k=2, provider="local"),
        ],
        providers={"anthropic": 1, "zai": 2, "local": 2},
        max_parallel=3,
    )
    harbor = FakeHarbor(delay=0.02)

    code = main(
        _run_args(store, arms, tmp_path / "out", tmp_path / "work"),
        deps=_deps(harbor=harbor),
    )

    assert code == 0
    assert harbor.calls == 8
    assert harbor.max_active <= 3
    assert harbor.max_by_provider["zai"] <= 2
    assert harbor.max_by_provider["local"] <= 2


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------


def _check_case(tmp_path: Path, *, total: int = 20, invalid: int = 0, infra: int = 0) -> Path:
    root = tmp_path / "check"
    for index in range(total):
        run_id = f"run-{index:02d}"
        write_run_doc(root, run_id, valid=index >= invalid)
        verdict = "error_infra" if index < infra else "reject"
        write_verdict_doc(
            root,
            run_id,
            arm_id="A1",
            task_id=f"t{index:02d}",
            repetition=1,
            attempt=1,
            verdict=verdict,
        )
    return root


def test_check_passes_at_exactly_95_valid_and_5_infra(tmp_path: Path) -> None:
    root = _check_case(tmp_path, invalid=1, infra=1)

    assert main(["check", str(root)]) == 0


def test_check_fails_when_valid_outputs_drop_below_95(tmp_path: Path) -> None:
    root = _check_case(tmp_path, invalid=2, infra=0)

    assert main(["check", str(root)]) == 1


def test_check_fails_when_error_infra_exceeds_5(tmp_path: Path) -> None:
    root = _check_case(tmp_path, invalid=0, infra=2)

    assert main(["check", str(root)]) == 1


def test_check_fails_when_a_run_has_no_verdict(tmp_path: Path) -> None:
    root = _check_case(tmp_path)
    (root / "verdicts" / "run-07.json").unlink()

    assert main(["check", str(root)]) == 1


def test_check_ignores_superseded_error_infra_attempts(tmp_path: Path) -> None:
    root = tmp_path / "check"
    write_run_doc(root, "run-1", valid=True)
    write_run_doc(root, "run-2", valid=True)
    write_verdict_doc(root, "run-1", attempt=1, verdict="error_infra")
    write_verdict_doc(root, "run-2", attempt=2, verdict="reject")

    assert main(["check", str(root)]) == 0


def test_check_fails_on_an_empty_matrix(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    (root / "runs").mkdir(parents=True)
    (root / "verdicts").mkdir()

    assert main(["check", str(root)]) == 1


def test_check_also_accepts_the_roadmap_flag(tmp_path: Path) -> None:
    root = _check_case(tmp_path, invalid=1, infra=1)

    assert main(["--check", str(root)]) == 0


# ---------------------------------------------------------------------------
# Run ids
# ---------------------------------------------------------------------------


def test_run_id_is_deterministic_and_schema_valid() -> None:
    task_id = "owner__repo-1234_with.dots-and-a-very-long-name-" + "x" * 40
    first = run_id_for("A1", task_id, 3, 2)
    second = run_id_for("A1", task_id, 3, 2)

    assert first == second
    assert len(first) <= 64
    assert re.fullmatch(r"^[a-z0-9][a-z0-9-]{7,63}$", first)
    assert first != run_id_for("A1", task_id + "-different", 3, 2)
