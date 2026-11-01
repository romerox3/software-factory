"""Tests for the deterministic spec-leak detector."""

from __future__ import annotations

from pathlib import Path

from factory.miner.leak import detect_leak


def make_base(tmp_path: Path, text: str) -> Path:
    base = tmp_path / "base"
    base.mkdir()
    (base / "calc.py").write_text(text, encoding="utf-8")
    return base


def test_detects_identifier_only_in_gold_added_lines_and_spec(tmp_path: Path) -> None:
    base = make_base(tmp_path, "def round_value(x):\n    return round(x)\n")
    gold = (
        "--- a/calc.py\n+++ b/calc.py\n@@ -1 +1 @@\n-    return round(x)\n+    return Decimal(x)\n"
    )

    assert detect_leak("Fix it with Decimal.", gold, base) == ["Decimal"]


def test_ignores_identifiers_that_already_exist_in_base(tmp_path: Path) -> None:
    base = make_base(tmp_path, "def quantize(x):\n    return x\n")
    gold = "+    return quantize(x)\n"

    assert detect_leak("Keep using quantize.", gold, base) == []


def test_ignores_identifiers_the_spec_does_not_mention(tmp_path: Path) -> None:
    base = make_base(tmp_path, "def round_value(x):\n    return x\n")
    gold = "+    return Decimal(x)\n"

    assert detect_leak("Round ties away from zero.", gold, base) == []


def test_returns_sorted_identifiers_and_skips_diff_headers(tmp_path: Path) -> None:
    base = make_base(tmp_path, "def round_value(x):\n    return x\n")
    gold = "+++ b/calc.py\n+    value = ROUND_HALF_UP\n+    return Decimal(value)\n"

    assert detect_leak("Use Decimal with ROUND_HALF_UP.", gold, base) == [
        "Decimal",
        "ROUND_HALF_UP",
    ]
