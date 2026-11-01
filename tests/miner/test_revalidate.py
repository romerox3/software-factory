"""End-to-end tests for task revalidation on the py-calc fixture."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

import factory.miner.revalidate as revalidate_module
from factory.miner.revalidate import _derive, revalidate
from factory.miner.runner import LocalRunner, RunnerError
from factory.tasks.workdir import DEFAULT_WORKDIR

REPO_ROOT = Path(__file__).parents[2]
PY_CALC = REPO_ROOT / "fixtures" / "repos" / "py-calc"
ROUND_TASK = REPO_ROOT / "fixtures" / "tasks" / "py-calc-round"
FLAKY_TASK = Path(__file__).parent / "data" / "py-calc-flaky"
TASK_ID = "py-calc-round"
TEST_COMMAND = "python -m pytest -q --junitxml=junit.xml -p no:cacheprovider"

PASSING_TEST_PATCH = """diff --git a/tests/test_calc.py b/tests/test_calc.py
--- a/tests/test_calc.py
+++ b/tests/test_calc.py
@@ -39,3 +39,7 @@ def test_round_half_up_above_half() -> None:
 
 def test_round_half_up_one_digit() -> None:
     assert round_half_up(1.24, 1) == 1.2
+
+
+def test_add_zero() -> None:
+    assert add(0, 0) == 0
"""

ALWAYS_FAILING_TEST_PATCH = """diff --git a/tests/test_known_broken.py b/tests/test_known_broken.py
new file mode 100644
--- /dev/null
+++ b/tests/test_known_broken.py
@@ -0,0 +1,2 @@
+def test_always_fails() -> None:
+    assert False
"""

BROKEN_GOLD_PATCH = """diff --git a/src/calc/__init__.py b/src/calc/__init__.py
--- a/src/calc/__init__.py
+++ b/src/calc/__init__.py
@@ -100,3 +100,4 @@
 this context does not exist
+import decimal
"""


def copy_round_task(store: Path) -> None:
    shutil.copytree(ROUND_TASK, store, dirs_exist_ok=True)
    verifier_path = store / "hidden" / TASK_ID / "verifier.json"
    verifier = json.loads(verifier_path.read_text(encoding="utf-8"))
    verifier["test_command"] = TEST_COMMAND
    verifier["junit_path"] = "junit.xml"
    verifier_path.write_text(json.dumps(verifier, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def test_revalidation_passes_the_task_workdir_to_the_runner(tmp_path: Path) -> None:
    store = tmp_path / "store"
    copy_round_task(store)
    task_path = store / "visible" / TASK_ID / "factory.task.json"
    task = read_json(task_path)
    task["repo"]["workdir"] = "/testbed"
    task_path.write_text(json.dumps(task), encoding="utf-8")

    class RecordingRunner:
        def __init__(self) -> None:
            self.inner = LocalRunner()
            self.workdirs: list[str] = []

        def run(self, repo_dir, test_command, junit_path, timeout_sec, *, workdir=DEFAULT_WORKDIR):
            self.workdirs.append(workdir)
            return self.inner.run(repo_dir, test_command, junit_path, timeout_sec)

    runner = RecordingRunner()

    result = revalidate(store, TASK_ID, PY_CALC, runner, seed=1)

    assert result["valid"] is True
    assert runner.workdirs == ["/testbed"] * 6


def test_round_fixture_revalidates_as_valid(tmp_path: Path) -> None:
    store = tmp_path / "store"
    copy_round_task(store)

    result = revalidate(store, TASK_ID, PY_CALC, LocalRunner(), seed=7)

    assert result["valid"] is True
    assert result["reason"] == "ok"
    assert set(result["f2p"]) == set(read_json(ROUND_TASK / "hidden" / TASK_ID / "f2p.json"))
    assert set(result["p2p"]) == set(read_json(ROUND_TASK / "hidden" / TASK_ID / "p2p.json"))
    assert result["flaky"] == []
    assert read_json(store / "hidden" / TASK_ID / "f2p.json") == result["f2p"]
    assert read_json(store / "hidden" / TASK_ID / "p2p.json") == result["p2p"]
    assert result["known_failures"] == []
    assert read_json(store / "hidden" / TASK_ID / "known_failures.json") == []
    assert read_json(store / "hidden" / TASK_ID / "revalidation.json") == result


def test_a_test_broken_in_every_run_is_a_known_failure(tmp_path: Path) -> None:
    store = tmp_path / "store"
    copy_round_task(store)
    patch = store / "hidden" / TASK_ID / "test.patch"
    patch.write_text(
        patch.read_text(encoding="utf-8") + ALWAYS_FAILING_TEST_PATCH, encoding="utf-8"
    )

    result = revalidate(store, TASK_ID, PY_CALC, LocalRunner(), seed=1)

    assert result["valid"] is True
    assert result["known_failures"] == ["tests/test_known_broken.py::test_always_fails"]
    assert read_json(store / "hidden" / TASK_ID / "known_failures.json") == result["known_failures"]


def test_a_failure_that_only_appears_in_some_runs_is_not_a_known_failure() -> None:
    runs: dict[str, list[dict[str, Any]]] = {
        "base": [{"tests::test_a": "failed"} for _ in range(3)],
        "gold": [
            {"tests::test_a": "failed"},
            {"tests::test_a": "passed"},
            {"tests::test_a": "failed"},
        ],
    }

    _, _, flaky, known_failures = _derive(runs)

    assert flaky == ["tests::test_a"]
    assert known_failures == []


def test_flaky_task_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = tmp_path / "store"
    shutil.copytree(FLAKY_TASK, store, dirs_exist_ok=True)
    monkeypatch.setenv("FLAKY_COUNTER", str(tmp_path / "counter"))

    result = revalidate(store, "py-calc-flaky", PY_CALC, LocalRunner(), seed=1)

    assert result["valid"] is False
    assert result["reason"] == "flaky"
    assert "tests/test_calc.py::test_alternates_between_runs" in result["flaky"]
    assert result["repro_test_id"] is None
    assert not (store / "visible" / "py-calc-flaky" / "snapshot").exists()


def test_empty_f2p_is_rejected(tmp_path: Path) -> None:
    store = tmp_path / "store"
    copy_round_task(store)
    (store / "hidden" / TASK_ID / "test.patch").write_text(PASSING_TEST_PATCH, encoding="utf-8")

    result = revalidate(store, TASK_ID, PY_CALC, LocalRunner(), seed=1)

    assert result["valid"] is False
    assert result["reason"] == "no_f2p"
    assert result["f2p"] == []
    assert not (store / "visible" / TASK_ID / "snapshot").exists()


def test_unapplicable_gold_patch_is_rejected(tmp_path: Path) -> None:
    store = tmp_path / "store"
    copy_round_task(store)
    (store / "hidden" / TASK_ID / "gold.patch").write_text(BROKEN_GOLD_PATCH, encoding="utf-8")

    result = revalidate(store, TASK_ID, PY_CALC, LocalRunner(), seed=1)

    assert result["valid"] is False
    assert result["reason"] == "patch_failed"
    assert result["runs"] == {"base": [], "gold": []}


def test_scratch_directories_live_under_the_given_root(tmp_path: Path) -> None:
    store = tmp_path / "store"
    copy_round_task(store)
    scratch = tmp_path / "scratch"
    seen: list[Path] = []

    class RecordingRunner:
        def __init__(self) -> None:
            self.inner = LocalRunner()

        def run(self, repo_dir, test_command, junit_path, timeout_sec, *, workdir=DEFAULT_WORKDIR):
            seen.append(Path(repo_dir))
            return self.inner.run(repo_dir, test_command, junit_path, timeout_sec)

    result = revalidate(store, TASK_ID, PY_CALC, RecordingRunner(), seed=1, tmp_root=scratch)

    assert result["valid"] is True
    assert {path.resolve().parent.parent for path in seen} == {scratch.resolve()}
    assert list(scratch.resolve().iterdir()) == []


def test_a_failed_copy_leaves_no_scratch_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "store"
    copy_round_task(store)
    scratch = tmp_path / "scratch"

    def broken_copy(source: Path, dest: Path, **_kwargs: object) -> None:
        Path(dest).mkdir(parents=True)
        (Path(dest) / "half").write_bytes(b"x" * 1024)
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(revalidate_module.shutil, "copytree", broken_copy)

    with pytest.raises(OSError, match="No space left"):
        revalidate(store, TASK_ID, PY_CALC, LocalRunner(), seed=1, tmp_root=scratch)

    assert list(scratch.resolve().iterdir()) == []


def test_runner_error_is_recorded_with_a_truncated_detail(tmp_path: Path) -> None:
    store = tmp_path / "store"
    copy_round_task(store)
    message = "docker died: " + "x" * 5000

    class FailingRunner:
        def run(self, *_args: object, **_kwargs: object) -> dict[str, Any]:
            raise RunnerError(message)

    result = revalidate(store, TASK_ID, PY_CALC, FailingRunner(), seed=1)

    assert result["valid"] is False
    assert result["reason"] == "runner_error"
    assert result["detail"] == message[:2000]
    assert read_json(store / "hidden" / TASK_ID / "revalidation.json")["detail"] == result["detail"]


def test_spec_leak_is_rejected(tmp_path: Path) -> None:
    store = tmp_path / "store"
    copy_round_task(store)
    proposal = store / "visible" / TASK_ID / "openspec" / "changes" / TASK_ID / "proposal.md"
    proposal.write_text("The fix uses `Decimal` to round the value.\n", encoding="utf-8")

    result = revalidate(store, TASK_ID, PY_CALC, LocalRunner(), seed=1)

    assert result["valid"] is False
    assert result["reason"] == "spec_leak"
    assert result["f2p"]
    assert not (store / "visible" / TASK_ID / "snapshot").exists()


def test_valid_task_snapshot_has_a_single_commit(tmp_path: Path) -> None:
    store = tmp_path / "store"
    copy_round_task(store)

    result = revalidate(store, TASK_ID, PY_CALC, LocalRunner(), seed=1)

    assert result["valid"] is True
    snapshot = store / "visible" / TASK_ID / "snapshot"
    commits = git(snapshot, "log", "--all", "--format=%H").splitlines()
    assert len(commits) == 1
    assert git(snapshot, "status", "--porcelain") == ""
    assert (snapshot / "src" / "calc" / "__init__.py").is_file()


def test_revalidation_is_deterministic_for_the_same_seed(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    copy_round_task(first)
    copy_round_task(second)

    first_result = revalidate(first, TASK_ID, PY_CALC, LocalRunner(), seed=1)
    second_result = revalidate(second, TASK_ID, PY_CALC, LocalRunner(), seed=1)

    assert first_result == second_result
    assert first_result["repro_test_id"] in first_result["f2p"]
    assert (first / "hidden" / TASK_ID / "revalidation.json").read_bytes() == (
        second / "hidden" / TASK_ID / "revalidation.json"
    ).read_bytes()


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()
