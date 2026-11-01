"""The audit gate must fail on false accepts, weak reject concordance or doubts."""

from pathlib import Path

import pytest

from factory.metrics.audit import main, read_sheet

DATA = Path(__file__).parent / "data" / "audit"


@pytest.mark.parametrize(
    ("sheet", "expected"),
    [
        ("pass.csv", 0),
        ("false_accepts.csv", 1),
        ("doubtful.csv", 1),
    ],
)
def test_audit_exit_codes(sheet: str, expected: int) -> None:
    assert main(["--sheet", str(DATA / sheet)]) == expected


def test_clean_sheet_counts() -> None:
    result = read_sheet(DATA / "pass.csv")

    assert result.accepts == 3
    assert result.false_accepts == ()
    assert result.rejects == 10
    assert result.concordant_rejects == 10
    assert result.reject_concordance == 1.0
    assert result.doubtful == ()
    assert result.passed is True


def test_false_accepts_are_listed() -> None:
    result = read_sheet(DATA / "false_accepts.csv")

    assert result.false_accepts == ("bad-accept-1", "bad-accept-2")
    assert result.passed is False
