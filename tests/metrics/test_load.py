"""Loading runs and verdicts must join by run id and separate error_infra."""

import json
from pathlib import Path

import pytest

from factory.metrics.load import load_dataset

DATA = Path(__file__).parent / "data"


def _write_dataset(root: Path, diff: bytes) -> None:
    (root / "runs").mkdir()
    (root / "verdicts").mkdir()
    (root / "diffs").mkdir()
    (root / "diffs" / "r1.patch").write_bytes(diff)
    run = {
        "run_id": "r1",
        "diff": {"uri": "diffs/r1.patch"},
        "cost": {"usd_real": 0.1, "usd_shadow": 0.0},
    }
    verdict = {
        "run_id": "r1",
        "task_id": "t1",
        "arm": "A1",
        "attempt": 1,
        "repetition": 1,
        "verdict": "accept",
        "verify_cost_usd": 0.01,
    }
    (root / "runs" / "r1.json").write_text(json.dumps(run), encoding="utf-8")
    (root / "verdicts" / "r1.json").write_text(json.dumps(verdict), encoding="utf-8")


def test_joins_runs_with_verdicts_by_run_id() -> None:
    dataset = load_dataset(DATA / "basic")

    assert len(dataset.records) == 18
    assert dataset.error_infra == ()

    record = next(item for item in dataset.records if item.run_id == "a1-t2-r1")
    assert (record.task_id, record.arm, record.repetition, record.verdict) == (
        "t2",
        "A1",
        1,
        "accept",
    )
    assert record.cost_usd == pytest.approx(0.20)
    assert record.verify_cost_usd == pytest.approx(0.01)
    assert record.category is None
    assert record.canary is False
    assert record.diff_text is not None


def test_error_infra_is_excluded_from_records_and_counted() -> None:
    dataset = load_dataset(DATA / "infra")

    assert len(dataset.records) == 2
    assert [record.run_id for record in dataset.error_infra] == ["infra-r2"]
    assert dataset.error_infra_count("A1") == 1
    assert dataset.error_infra_count("A2") == 0


def test_diff_keeps_crlf_line_endings(tmp_path: Path) -> None:
    diff = (
        b"diff --git a/app.py b/app.py\r\n"
        b"--- a/app.py\r\n"
        b"+++ b/app.py\r\n"
        b"@@ -1,2 +1,3 @@\r\n"
        b" def check(x):\r\n"
        b"+    return x\r\n"
        b" \r\n"
    )
    _write_dataset(tmp_path, diff)

    record = load_dataset(tmp_path).records[0]

    assert record.diff_text is not None
    assert "\r\n" in record.diff_text
    assert record.diff_text.encode("utf-8", "surrogateescape") == diff


def test_diff_with_non_utf8_bytes_round_trips(tmp_path: Path) -> None:
    diff = (
        b"diff --git a/app.py b/app.py\n"
        b"--- a/app.py\n"
        b"+++ b/app.py\n"
        b"@@ -1,1 +1,1 @@\n"
        b"-\xff old\n"
        b"+caf\xe9\n"
    )
    _write_dataset(tmp_path, diff)

    record = load_dataset(tmp_path).records[0]

    assert record.diff_text is not None
    assert record.diff_text.encode("utf-8", "surrogateescape") == diff
