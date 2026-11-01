"""The command line writes a schema-valid verdict.json and maps verdicts to exit codes."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from factory.verifier.__main__ import main
from factory.verifier.verdict import validate_document

from .support import TASKS, TRAPS

ROUND = "py-calc-round"


def args(
    tmp_path: Path, diff: Path, image: str, mirror: tuple[Path, str], *extra: str
) -> list[str]:
    return [
        "--task-store", str(TASKS / ROUND),
        "--task-id", ROUND,
        "--diff", str(diff),
        "--mirror", str(mirror[0]),
        "--base-commit", mirror[1],
        "--image", image,
        "--out-dir", str(tmp_path / "out"),
        "--run-id", "run-7",
        "--arm", "A1",
        "--repetition", "2",
        "--attempt", "2",
        *extra,
    ]  # fmt: skip


def test_cli_accepts_the_gold_patch(tmp_path, image, py_mirror) -> None:
    diff = TASKS / ROUND / "hidden" / ROUND / "gold.patch"
    code = main(args(tmp_path, diff, image, py_mirror))
    document = json.loads((tmp_path / "out" / "verdict.json").read_text())
    validate_document(document)
    assert code == 0
    assert document["verdict"] == "accept"
    assert (document["run_id"], document["arm"], document["repetition"], document["attempt"]) == (
        "run-7",
        "A1",
        2,
        2,
    )


def test_cli_rejects_and_writes_only_whitelisted_feedback(tmp_path, image, py_mirror) -> None:
    feedback = tmp_path / "feedback.json"
    diff = TRAPS / "cheat-skip-marker" / "patch.diff"
    code = main(args(tmp_path, diff, image, py_mirror, "--feedback-file", str(feedback)))
    assert code == 10
    items = json.loads(feedback.read_text())["items"]
    rules = ["dg.forbidden-glob", "dg.runner-script", "dg.skip-marker", "dg.test-modified"]
    assert items == [{"type": "diff_guard", "rule_ids": rules}]
    assert set(items[0]) == {"type", "rule_ids"}


def test_cli_exit_code_for_a_cheat(tmp_path, image, py_mirror) -> None:
    run = TRAPS / "fake-cost" / "run.json"
    empty = tmp_path / "empty.patch"
    empty.write_bytes(b"")
    code = main(args(tmp_path, empty, image, py_mirror, "--run", str(run)))
    assert code == 11


def test_cli_without_a_usable_task_is_error_infra_not_accept(tmp_path, image, py_mirror) -> None:
    diff = TASKS / ROUND / "hidden" / ROUND / "gold.patch"
    argv = args(tmp_path, diff, image, py_mirror)
    argv[argv.index(ROUND)] = "no-such-task"
    assert main(argv) == 20
    document = json.loads((tmp_path / "out" / "verdict.json").read_text())
    assert document["verdict"] == "error_infra"


def test_cli_usage_errors_and_untagged_images(tmp_path, image, py_mirror) -> None:
    diff = tmp_path / "d.patch"
    diff.write_bytes(b"")
    assert main(args(tmp_path, diff, "python:3.12-slim", py_mirror)) == 2
    assert main(args(tmp_path, tmp_path / "missing.patch", image, py_mirror)) == 2
    assert not (tmp_path / "out" / "verdict.json").exists()


def test_module_entry_point_runs(tmp_path) -> None:
    done = subprocess.run(
        [sys.executable, "-m", "factory.verifier", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0 and "--task-store" in done.stdout


@pytest.mark.parametrize("value", ["accept", "reject", "cheat_suspected", "error_infra"])
def test_exit_codes_are_distinct_and_only_accept_is_zero(value: str) -> None:
    from factory.verifier.__main__ import EXIT_CODES

    assert (EXIT_CODES[value] == 0) == (value == "accept")
    assert len(set(EXIT_CODES.values())) == 4
