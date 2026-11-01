"""The report must write both formats and enforce the F0 exit criteria."""

import json
from pathlib import Path

import pytest

from factory.metrics.report import EXIT_CRITERIA, main

DATA = Path(__file__).parent / "data"
BASIC = DATA / "basic"

VALUES = {
    "valid_tasks": "30",
    "contract_valid_rate": "99.2%",
    "error_infra_rate": "1.7%",
    "verifier_reproducibility": "99.5%",
    "false_accepts": "1",
    "reject_concordance": "9/10",
    "m4_baseline": "1.3",
}


def _criteria_report(keys: tuple[str, ...]) -> str:
    lines = ["# F0 report", "", "| Criterion | Value |", "|---|---|"]
    lines.extend(f"| {key} | {VALUES[key]} |" for key in keys)
    return "\n".join(lines) + "\n"


def test_report_writes_markdown_and_json(tmp_path: Path) -> None:
    prefix = tmp_path / "f0"

    code = main(
        [
            "--runs",
            str(BASIC),
            "--gold",
            str(BASIC / "gold.json"),
            "--out",
            str(prefix),
        ]
    )

    assert code == 0
    markdown = Path(f"{prefix}.md").read_text(encoding="utf-8")
    assert "| Arm | pass@1 | pass^3 |" in markdown
    assert "Paired bootstrap of pass@1 vs A1" in markdown

    payload = json.loads(Path(f"{prefix}.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1"
    assert payload["k"] == 3
    assert payload["arms"]["A1"]["pass_at_1"] == pytest.approx(5 / 9)
    assert payload["arms"]["A1"]["m1_gen"] == pytest.approx(0.27)
    assert payload["arms"]["A2"]["m1_total"] == pytest.approx(1.68)
    assert set(payload["bootstrap_vs_A1"]) == {"A2"}


def test_check_accepts_a_complete_report(tmp_path: Path) -> None:
    report = tmp_path / "complete.md"
    report.write_text(_criteria_report(EXIT_CRITERIA), encoding="utf-8")

    assert main(["--check", str(report)]) == 0


def test_check_rejects_a_missing_key(tmp_path: Path) -> None:
    report = tmp_path / "incomplete.md"
    report.write_text(
        _criteria_report(tuple(key for key in EXIT_CRITERIA if key != "m4_baseline")),
        encoding="utf-8",
    )

    assert main(["--check", str(report)]) == 1
