"""The report must write both formats and enforce the per-phase exit criteria."""

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
    "best_arm_pass_at_1": "23.4%",
    "m4_baseline": "1.3",
}


def _criteria_report(keys: tuple[str, ...]) -> str:
    lines = ["# F0 report", "", "| Criterion | Value |", "|---|---|"]
    lines.extend(f"| {key} | {VALUES[key]} |" for key in keys)
    return "\n".join(lines) + "\n"


_SOURCE = """def check(x):
    if x:
        return 1
    return 0
"""

_GOLD_DIFF = """diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,4 +1,6 @@
 def check(x):
     if x:
         return 1
+    if x > 100:
+        return 2
     return 0
"""

_CANDIDATE_DIFF = """diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,4 +1,8 @@
 def check(x):
     if x:
         return 1
+    if x > 10:
+        return 2
+    if x > 20:
+        return 3
     return 0
"""


def _maintainable_dataset(root: Path) -> Path:
    """One accepted run whose candidate and gold diffs apply to their snapshot."""
    for directory in ("runs", "verdicts", "diffs"):
        (root / directory).mkdir(parents=True)
    src = root / "sources" / "t1" / "snapshot" / "src"
    src.mkdir(parents=True)
    (src / "app.py").write_text(_SOURCE, encoding="utf-8")
    (root / "diffs" / "run1.patch").write_text(_CANDIDATE_DIFF, encoding="utf-8")
    (root / "gold.json").write_text(json.dumps({"t1": _GOLD_DIFF}), encoding="utf-8")

    run = {
        "schema_version": "0.1",
        "run_id": "run1",
        "exit": "done",
        "diff": {
            "uri": "diffs/run1.patch",
            "sha256": "sha256:0",
            "files_changed": 1,
            "lines_added": 4,
            "lines_removed": 0,
        },
        "cost": {"usd_real": 0.10, "usd_shadow": 0.0, "source": "gateway"},
    }
    verdict = {
        "schema_version": "1",
        "run_id": "run1",
        "task_id": "t1",
        "arm": "A1",
        "attempt": 1,
        "repetition": 1,
        "verdict": "accept",
        "reason": "tests pass",
        "verify_cost_usd": 0.01,
        "diff_sha": "sha256:0",
    }
    (root / "runs" / "run1.json").write_text(json.dumps(run), encoding="utf-8")
    (root / "verdicts" / "run1.json").write_text(json.dumps(verdict), encoding="utf-8")
    return root


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
    assert "| M7a | M7b | M7c |" in markdown
    assert "Paired bootstrap of pass@1 vs A1" in markdown

    payload = json.loads(Path(f"{prefix}.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1"
    assert payload["k"] == 3
    assert payload["arms"]["A1"]["pass_at_1"] == pytest.approx(5 / 9)
    assert payload["arms"]["A1"]["m1_gen"] == pytest.approx(0.27)
    assert payload["arms"]["A1"]["m7a"] is None
    assert payload["arms"]["A1"]["m7b"] is None
    assert payload["arms"]["A1"]["m7c"] == pytest.approx(1.0)
    assert payload["arms"]["A2"]["m1_total"] == pytest.approx(1.68)
    assert set(payload["bootstrap_vs_A1"]) == {"A2"}


def test_report_with_sources_fills_every_m7_value(tmp_path: Path) -> None:
    prefix = tmp_path / "f0"
    dataset = _maintainable_dataset(tmp_path / "dataset")

    code = main(
        [
            "--runs",
            str(dataset),
            "--gold",
            str(dataset / "gold.json"),
            "--sources",
            str(dataset / "sources"),
            "--out",
            str(prefix),
        ]
    )

    assert code == 0
    payload = json.loads(Path(f"{prefix}.json").read_text(encoding="utf-8"))
    arm = payload["arms"]["A1"]
    assert arm["m7a"] == pytest.approx(1.0)
    assert arm["m7b"] == pytest.approx(0.0)
    assert arm["m7c"] == pytest.approx(2.0)


def test_check_accepts_a_complete_phase_a_report(tmp_path: Path) -> None:
    report = tmp_path / "complete.md"
    report.write_text(_criteria_report(EXIT_CRITERIA["A"]), encoding="utf-8")

    assert main(["--check", str(report)]) == 0
    assert main(["--check", str(report), "--phase", "A"]) == 0


def test_check_rejects_a_missing_key(tmp_path: Path) -> None:
    report = tmp_path / "incomplete.md"
    report.write_text(
        _criteria_report(tuple(key for key in EXIT_CRITERIA["A"] if key != "best_arm_pass_at_1")),
        encoding="utf-8",
    )

    assert main(["--check", str(report)]) == 1


def test_phase_c_uses_its_own_criteria(tmp_path: Path) -> None:
    report = tmp_path / "phase-c.md"
    report.write_text(_criteria_report(EXIT_CRITERIA["C"]), encoding="utf-8")

    assert main(["--check", str(report), "--phase", "C"]) == 0
    assert main(["--check", str(report)]) == 1
