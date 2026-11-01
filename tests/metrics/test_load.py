"""Loading runs and verdicts must join by run id and separate error_infra."""

from pathlib import Path

import pytest

from factory.metrics.load import load_dataset

DATA = Path(__file__).parent / "data"


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
    assert record.diff_text is not None


def test_error_infra_is_excluded_from_records_and_counted() -> None:
    dataset = load_dataset(DATA / "infra")

    assert len(dataset.records) == 2
    assert [record.run_id for record in dataset.error_infra] == ["infra-r2"]
    assert dataset.error_infra_count("A1") == 1
    assert dataset.error_infra_count("A2") == 0
