"""Revalidate a task in the verifier environment before publishing it.

The recipe is docs/06-harness-and-tasks.md §2.2, steps 5-8 and 10-11: apply the
test patch to the base repo and run the tests several times, then apply the gold
patch and repeat, derive F2P/P2P, reject flaky or leaking tasks, and write the
derived lists plus a fresh-init snapshot of the base for the visible task.
"""

from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from factory.junit import Status
from factory.miner.leak import detect_leak
from factory.miner.runner import RunnerError, TestRunner, remove_tree
from factory.snapshot.fresh_init import build_snapshot
from factory.tasks.workdir import DEFAULT_WORKDIR, workdir_of

_MISSING = "missing"
_FAILING_STATES = frozenset({"failed", "error", _MISSING})


class PatchError(RuntimeError):
    """A patch does not apply to the base tree."""


def revalidate(
    store: Path,
    task_id: str,
    base_repo: Path,
    runner: TestRunner,
    *,
    repetitions: int = 3,
    seed: int,
) -> dict[str, Any]:
    """Validate ``task_id`` against ``base_repo`` and record the outcome."""
    if repetitions < 1:
        raise ValueError(f"repetitions must be positive: {repetitions}")
    store = Path(store)
    base_repo = Path(base_repo)
    hidden = store / "hidden" / task_id
    visible = store / "visible" / task_id
    proposal_path = visible / "openspec" / "changes" / task_id / "proposal.md"
    test_patch = hidden / "test.patch"
    gold_patch = hidden / "gold.patch"
    verifier = json.loads((hidden / "verifier.json").read_text(encoding="utf-8"))
    test_command = str(verifier["test_command"])
    junit_path = str(verifier["junit_path"])
    timeout_sec = int(verifier["timeout_sec"])
    workdir = _workdir(visible / "factory.task.json")

    runs: dict[str, list[dict[str, Status]]] = {"base": [], "gold": []}
    result: dict[str, Any] = {
        "valid": False,
        "reason": None,
        "f2p": [],
        "p2p": [],
        "flaky": [],
        "repro_test_id": None,
        "repetitions": repetitions,
        "runs": runs,
    }

    tmp = Path(tempfile.mkdtemp(prefix="factory-revalidate-"))
    try:
        base_work = tmp / "base"
        gold_work = tmp / "gold"
        _copy_repo(base_repo, base_work)
        _copy_repo(base_repo, gold_work)
        try:
            _apply_patch(base_work, test_patch)
            _apply_patch(gold_work, test_patch)
            _apply_patch(gold_work, gold_patch)
        except PatchError:
            result["reason"] = "patch_failed"
            _write_json(hidden / "revalidation.json", result)
            return result

        try:
            for _ in range(repetitions):
                runs["base"].append(
                    runner.run(base_work, test_command, junit_path, timeout_sec, workdir=workdir)
                )
            for _ in range(repetitions):
                runs["gold"].append(
                    runner.run(gold_work, test_command, junit_path, timeout_sec, workdir=workdir)
                )
        except RunnerError:
            result["reason"] = "runner_error"
            _write_json(hidden / "revalidation.json", result)
            return result
    finally:
        remove_tree(tmp)

    f2p, p2p, flaky = _derive(runs)
    result["f2p"] = f2p
    result["p2p"] = p2p
    result["flaky"] = flaky

    if not f2p:
        result["reason"] = "no_f2p"
    elif flaky:
        result["reason"] = "flaky"
    elif detect_leak(
        proposal_path.read_text(encoding="utf-8"),
        gold_patch.read_text(encoding="utf-8"),
        base_repo,
    ):
        result["reason"] = "spec_leak"
    else:
        _write_json(hidden / "f2p.json", f2p)
        _write_json(hidden / "p2p.json", p2p)
        _write_snapshot(base_repo, visible / "snapshot")
        rng = random.Random(f"{seed}:{task_id}")
        if rng.random() < 0.3:
            result["repro_test_id"] = rng.choice(f2p)
        result["valid"] = True
        result["reason"] = "ok"

    _write_json(hidden / "revalidation.json", result)
    return result


def _workdir(task_path: Path) -> str:
    """Read ``repo.workdir`` from the visible task written by the importer."""
    try:
        document = json.loads(task_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return DEFAULT_WORKDIR
    return workdir_of(document)


def _derive(
    runs: dict[str, list[dict[str, Status]]],
) -> tuple[list[str], list[str], list[str]]:
    """Return ``(f2p, p2p, flaky)`` from the per-run status maps."""
    base_runs = runs["base"]
    gold_runs = runs["gold"]
    test_ids = sorted({test_id for run in [*base_runs, *gold_runs] for test_id in run})

    f2p: list[str] = []
    p2p: list[str] = []
    flaky: list[str] = []
    for test_id in test_ids:
        base_states = [run.get(test_id, _MISSING) for run in base_runs]
        gold_states = [run.get(test_id, _MISSING) for run in gold_runs]
        if len(set(base_states)) > 1 or len(set(gold_states)) > 1:
            flaky.append(test_id)
        if all(state in _FAILING_STATES for state in base_states) and all(
            state == "passed" for state in gold_states
        ):
            f2p.append(test_id)
        if all(state == "passed" for state in [*base_states, *gold_states]):
            p2p.append(test_id)
    return f2p, p2p, flaky


def _copy_repo(source: Path, dest: Path) -> None:
    shutil.copytree(
        source,
        dest,
        ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"),
    )


def _apply_patch(work: Path, patch: Path) -> None:
    text = patch.read_text(encoding="utf-8")
    if not text.strip():
        return
    result = subprocess.run(
        ["git", "apply", "--whitespace=nowarn", str(patch.resolve())],
        cwd=work,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = (result.stderr or "").strip() or "git apply wrote nothing"
        raise PatchError(f"{patch.name} does not apply: {stderr}")


def _write_snapshot(base_repo: Path, dest: Path) -> None:
    """Create ``dest`` as a single-commit fresh-init snapshot of ``base_repo``."""
    with tempfile.TemporaryDirectory(prefix="factory-revalidate-source-") as tmp:
        source = Path(tmp) / "source"
        _copy_repo(base_repo, source)
        _commit_base(source)
        if dest.exists():
            shutil.rmtree(dest)
        build_snapshot(source, "HEAD", dest)


def _commit_base(repo: Path) -> None:
    """Initialize ``repo`` and commit its tree with a fixed identity."""
    env = os.environ.copy()
    env.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "factory",
            "GIT_AUTHOR_EMAIL": "factory@invalid",
            "GIT_COMMITTER_NAME": "factory",
            "GIT_COMMITTER_EMAIL": "factory@invalid",
        }
    )
    _git(["init", "-q", "--template=", "-b", "main"], repo, env)
    _git(["add", "-A", "-f"], repo, env)
    _git(
        ["-c", "commit.gpgsign=false", "commit", "-q", "--no-verify", "-m", "base"],
        repo,
        env,
    )


def _git(args: list[str], cwd: Path, env: dict[str, str]) -> None:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = (result.stderr or "").strip() or "(git wrote nothing to stderr)"
        raise RuntimeError(f"git {' '.join(args)} failed: {stderr}")


def _write_json(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
