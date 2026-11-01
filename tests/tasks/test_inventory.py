"""The inventory gate must count only revalidated tasks, per language."""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]


def add_task(store: Path, task_id: str, framework: str, *, valid: bool | None = True) -> None:
    hidden = store / "hidden" / task_id
    hidden.mkdir(parents=True)
    (hidden / "verifier.json").write_text(json.dumps({"framework": framework}), encoding="utf-8")
    if valid is not None:
        (hidden / "revalidation.json").write_text(json.dumps({"valid": valid}), encoding="utf-8")


def make_store(tmp_path: Path) -> Path:
    store = tmp_path / "store"
    add_task(store, "py-task-1", "pytest")
    add_task(store, "py-task-2", "pytest")
    add_task(store, "ts-task-1", "vitest")
    add_task(store, "unvalidated-task", "pytest", valid=None)
    add_task(store, "invalid-task", "jest", valid=False)
    return store


def run_inventory(store: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "factory.tasks.inventory", "--store", str(store), *arguments],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_inventory_passes_when_the_minimums_are_met(tmp_path: Path) -> None:
    result = run_inventory(make_store(tmp_path), "--min-valid", "3")

    assert result.returncode == 0, result.stderr
    assert "py" in result.stdout
    assert "ts" in result.stdout
    assert "total" in result.stdout


def test_inventory_fails_when_a_language_minimum_is_missed(tmp_path: Path) -> None:
    result = run_inventory(make_store(tmp_path), "--min-valid", "3", "--min-lang", "ts=2")

    assert result.returncode == 1


def test_inventory_without_revalidated_tasks_fails(tmp_path: Path) -> None:
    store = tmp_path / "empty"
    add_task(store, "py-task-1", "pytest", valid=None)

    result = run_inventory(store, "--min-valid", "1")

    assert result.returncode == 1
