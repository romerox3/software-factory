"""Tests for the JUnit XML parser."""

from pathlib import Path

import pytest
from defusedxml.common import DefusedXmlException

from factory.junit import MAX_REPORT_BYTES, parse_junit

DATA_DIR = Path(__file__).parent / "data"


def test_pytest_report() -> None:
    assert parse_junit(DATA_DIR / "pytest.xml") == {
        "tests.test_calc.TestRound::test_half[2.5]": "passed",
        "tests.test_calc.TestRound::test_half[2.4]": "failed",
        "tests.test_calc.TestRound::test_half[bad]": "error",
        "tests.test_calc.TestRound::test_half[0]": "skipped",
    }


def test_jest_junit_report_collapses_whitespace_in_ids() -> None:
    assert parse_junit(DATA_DIR / "jest-junit.xml") == {
        "calc rounds half up::calc rounds half up rounds half up": "passed",
        "calc rounds half up::calc rounds half up keeps the sign": "failed",
        "calc rounds half up::calc rounds half up handles floats": "skipped",
    }


def test_vitest_report() -> None:
    assert parse_junit(DATA_DIR / "vitest.xml") == {
        "src/calc.test.ts::calc > rounds half up": "passed",
        "src/calc.test.ts::calc > rejects invalid input": "failed",
    }


def test_nested_testsuites() -> None:
    assert parse_junit(DATA_DIR / "nested.xml") == {
        "calc.Outside::test_half": "passed",
        "calc.Outer::test_half": "passed",
        "calc.Inner::test_half": "failed",
    }


def test_status_precedence_and_ignored_children() -> None:
    assert parse_junit(DATA_DIR / "mixed.xml") == {
        "calc.Round::test_error_wins": "error",
        "calc.Round::test_failure_beats_skipped": "failed",
        "calc.Round::test_only_skipped": "skipped",
        "calc.Round::test_noise_only": "passed",
    }


def test_missing_classname_falls_back_to_file_then_name(tmp_path: Path) -> None:
    report = tmp_path / "fallback.xml"
    report.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="calc">
  <testcase file="src/calc.test.ts" name="calc &gt; rounds half up" />
  <testcase name="standalone" />
</testsuite>
""",
        encoding="utf-8",
    )

    assert parse_junit(report) == {
        "src/calc.test.ts::calc > rounds half up": "passed",
        "standalone": "passed",
    }


def test_duplicate_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate test id"):
        parse_junit(DATA_DIR / "duplicate.xml")


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        ("passed", "failed", "failed"),
        ("failed", "passed", "failed"),
        ("passed", "skipped", "skipped"),
        ("failed", "error", "error"),
        ("passed", "passed", "passed"),
    ],
)
def test_repeated_ids_merge_to_the_worst_status(
    tmp_path: Path, first: str, second: str, expected: str
) -> None:
    report = tmp_path / "merged.xml"
    report.write_text(
        "<testsuite>"
        + _testcase("calc.Round", "test_half", first)
        + _testcase("calc.Round", "test_half", second)
        + "</testsuite>",
        encoding="utf-8",
    )

    assert parse_junit(report, merge_duplicates=True) == {"calc.Round::test_half": expected}


def test_merge_duplicates_accepts_the_duplicate_fixture() -> None:
    assert parse_junit(DATA_DIR / "duplicate.xml", merge_duplicates=True) == {
        "calc.Round::test_half": "passed"
    }


def _testcase(classname: str, name: str, status: str) -> str:
    body = {
        "passed": "",
        "failed": "<failure message='x'/>",
        "error": "<error message='x'/>",
        "skipped": "<skipped/>",
    }[status]
    return f'<testcase classname="{classname}" name="{name}">{body}</testcase>'


def test_dtd_with_entity_is_rejected() -> None:
    with pytest.raises(DefusedXmlException):
        parse_junit(DATA_DIR / "xxe.xml")


def test_dtd_without_entities_is_rejected(tmp_path: Path) -> None:
    report = tmp_path / "doctype.xml"
    report.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE testsuite SYSTEM "calc.dtd">
<testsuite name="calc"><testcase name="test_half" /></testsuite>
""",
        encoding="utf-8",
    )

    with pytest.raises(DefusedXmlException):
        parse_junit(report)


def test_oversized_report_is_rejected(tmp_path: Path) -> None:
    report = tmp_path / "big.xml"
    report.write_bytes(b" " * (MAX_REPORT_BYTES + 1))

    with pytest.raises(ValueError, match="exceeds"):
        parse_junit(report)
