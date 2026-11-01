"""Integrity tests for the F0-11 fixtures: trap repos, trap payloads and reference tasks.

The threat table in ``docs/05-verification-design.md`` is the source of truth:
every fixture it names must exist, carry the right threat id and apply or
validate against the contract the verifier will use.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from factory.junit import parse_junit

REPO_ROOT = Path(__file__).parents[2]
FIXTURES = REPO_ROOT / "fixtures"
TRAPS = FIXTURES / "traps"
REPOS = FIXTURES / "repos"
TASKS = FIXTURES / "tasks"
SCHEMAS = REPO_ROOT / "schemas"
DESIGN = REPO_ROOT / "docs" / "05-verification-design.md"
EXAMPLE_OUTPUT = REPO_ROOT / "examples" / "executor" / "claude-code.output.json"

TASK_IDS = ("py-calc-round", "py-calc-canary")
HIDDEN_FILES = {"test.patch", "gold.patch", "f2p.json", "p2p.json", "verifier.json"}
EXPECTED_VERDICTS = {"reject", "cheat_suspected", "accept", "error_infra"}
KINDS = {"diff", "run-output", "probe", "process"}

GIT = [
    "git",
    "-c",
    "user.name=fixture",
    "-c",
    "user.email=fixture@example.invalid",
    "-c",
    "commit.gpgsign=false",
]

THREAT_ROW = re.compile(r"^\|\s*(T\d{2})\s*\|")
BACKTICKED = re.compile(r"`([^`]+)`")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def threat_table() -> dict[str, list[str]]:
    """Map each threat id to the fixture names in the last column of its row."""
    rows: dict[str, list[str]] = {}
    for line in DESIGN.read_text(encoding="utf-8").splitlines():
        match = THREAT_ROW.match(line)
        if match:
            rows[match.group(1)] = BACKTICKED.findall(line.split("|")[-2])
    return rows


# Fixtures added by a later round that the last column of the table does not name yet (the
# documents are updated by the orchestrator, not by the round that adds the fixture). Once the
# table names one, its entry here is redundant and harmless; remove it then.
EXTRA_FIXTURES = {"forge-report-atexit": "T29"}

THREATS = threat_table()
for _name, _threat in EXTRA_FIXTURES.items():
    if _name not in THREATS[_threat]:
        THREATS[_threat].append(_name)
METAS: dict[str, dict[str, Any]] = {
    path.parent.name: load_json(path) for path in sorted(TRAPS.glob("*/meta.json"))
}
INDEX = load_json(TRAPS / "index.json")

TASK_SCHEMA = load_json(SCHEMAS / "task.schema.json")
VERIFIER_SCHEMA = load_json(SCHEMAS / "verifier-task.schema.json")
OUTPUT_SCHEMA = load_json(SCHEMAS / "executor-output.schema.json")

DIFF_FIXTURES = sorted(name for name, meta in METAS.items() if meta["kind"] == "diff")
RUN_FIXTURES = sorted(name for name, meta in METAS.items() if meta["kind"] == "run-output")


def test_threat_table_is_parsed() -> None:
    assert len(THREATS) == 30
    assert THREATS["T01"] == ["cheat-edit-test", "cheat-delete-test"]
    assert THREATS["T09"] == ["cheat-ignored-conftest"]
    assert THREATS["T26"] == []


def test_every_fixture_named_in_the_table_has_its_meta() -> None:
    expected = {name: threat for threat, names in THREATS.items() for name in names}
    assert set(METAS) == set(expected)
    for name, threat in expected.items():
        assert METAS[name]["threat"] == threat, name


def test_fixture_directories_are_exactly_the_named_fixtures() -> None:
    directories = {path.name for path in TRAPS.iterdir() if path.is_dir()}
    named = {name for names in THREATS.values() for name in names}
    assert directories == named


@pytest.mark.parametrize("name", sorted(METAS), ids=sorted(METAS))
def test_meta_has_the_documented_shape(name: str) -> None:
    meta = METAS[name]
    assert set(meta) == {"threat", "kind", "target_repo", "expect", "description"}
    assert meta["kind"] in {"diff", "run-output", "probe"}
    assert meta["target_repo"] in {"py-calc", "ts-calc", None}
    assert meta["expect"] in EXPECTED_VERDICTS
    assert meta["description"].strip()
    if meta["kind"] == "diff":
        assert (TRAPS / name / "patch.diff").is_file()
    if meta["kind"] == "run-output":
        assert (TRAPS / name / "run.json").is_file()
    if meta["kind"] == "probe":
        assert (TRAPS / name / "probe.sh").is_file()


def test_index_covers_all_threats_and_fixtures() -> None:
    entries = [(entry["threat"], entry["fixture"]) for entry in INDEX]
    expected = {(threat, name) for threat, names in THREATS.items() for name in (names or [None])}
    assert len(entries) == len(set(entries))
    assert {threat for threat, _ in entries} == set(THREATS)
    assert set(entries) == expected
    for entry in INDEX:
        assert entry["kind"] in KINDS
        if entry["fixture"] is None:
            assert entry["kind"] == "process"
        else:
            assert entry["kind"] == METAS[entry["fixture"]]["kind"]


def run_git(dest: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([*GIT, *args], cwd=dest, check=False, capture_output=True, text=True)


def base_copy(repo: str, dest: Path) -> Path:
    shutil.copytree(REPOS / repo, dest)
    run_git(dest, "init", "-q", "-b", "main")
    run_git(dest, "add", "-A", "-f")
    result = run_git(dest, "commit", "-q", "-m", "base")
    assert result.returncode == 0, result.stderr
    return dest


def apply_patch(dest: Path, patch: Path, *, check_only: bool = False) -> None:
    args = ["apply", str(patch)]
    if check_only:
        args.insert(1, "--check")
    result = run_git(dest, *args)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("name", DIFF_FIXTURES, ids=DIFF_FIXTURES)
def test_patch_applies_cleanly_to_its_target_repo(name: str, tmp_path: Path) -> None:
    target = METAS[name]["target_repo"]
    assert target in {"py-calc", "ts-calc"}
    work = base_copy(target, tmp_path / target)
    apply_patch(work, TRAPS / name / "patch.diff", check_only=True)


def test_run_output_contract_rejects_a_tampered_document() -> None:
    # Control: the validator used below must reject a document it must not accept.
    document = load_json(TRAPS / "empty-diff" / "run.json")
    document["cost"]["source"] = "agent"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(OUTPUT_SCHEMA).validate(document)


@pytest.mark.parametrize("name", RUN_FIXTURES, ids=RUN_FIXTURES)
def test_run_output_matches_the_executor_output_contract(name: str) -> None:
    document = load_json(TRAPS / name / "run.json")
    jsonschema.Draft202012Validator(OUTPUT_SCHEMA).validate(document)
    assert set(document) == set(load_json(EXAMPLE_OUTPUT))


def junit_id(pytest_id: str) -> str:
    path, _, test = pytest_id.partition("::")
    return f"{path.removesuffix('.py').replace('/', '.')}::{test}"


def pytest_statuses(work: Path, ids: list[str], report: Path) -> dict[str, str]:
    env = {
        **os.environ,
        "PYTHONPATH": str(work / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--junitxml={report}",
            *ids,
        ],
        cwd=work,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    return parse_junit(report)


def test_feasible_task_f2p_and_p2p(tmp_path: Path) -> None:
    hidden = TASKS / "py-calc-round" / "hidden" / "py-calc-round"
    f2p = load_json(hidden / "f2p.json")
    p2p = load_json(hidden / "p2p.json")
    assert f2p and p2p
    assert not set(f2p) & set(p2p)

    work = base_copy("py-calc", tmp_path / "py-calc")
    apply_patch(work, hidden / "test.patch")
    ids = [*f2p, *p2p]

    before = pytest_statuses(work, ids, tmp_path / "before.xml")
    assert set(before) == {junit_id(test_id) for test_id in ids}
    for test_id in f2p:
        assert before[junit_id(test_id)] == "failed", test_id
    for test_id in p2p:
        assert before[junit_id(test_id)] == "passed", test_id

    apply_patch(work, hidden / "gold.patch")
    after = pytest_statuses(work, ids, tmp_path / "after.xml")
    assert set(after) == {junit_id(test_id) for test_id in ids}
    for test_id in ids:
        assert after[junit_id(test_id)] == "passed", test_id


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_task_documents_validate(task_id: str) -> None:
    visible = TASKS / task_id / "visible" / task_id
    hidden = TASKS / task_id / "hidden" / task_id

    task = load_json(visible / "factory.task.json")
    jsonschema.Draft202012Validator(TASK_SCHEMA).validate(task)
    assert task["task_id"] == task_id

    verifier = load_json(hidden / "verifier.json")
    jsonschema.Draft202012Validator(VERIFIER_SCHEMA).validate(verifier)
    assert verifier["task_id"] == task_id


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_visible_tree_ships_no_hidden_material(task_id: str) -> None:
    visible = TASKS / task_id / "visible"
    shipped = {path.name for path in visible.rglob("*") if path.is_file()}
    assert shipped.isdisjoint(HIDDEN_FILES)

    hidden = TASKS / task_id / "hidden" / task_id
    assert {path.name for path in hidden.iterdir()} == HIDDEN_FILES
