"""Audit a sample of verifier verdicts against a human auditor.

``python -m factory.metrics.audit --sheet audit.csv`` reads a CSV with the
columns ``run_id, verdict, auditor_verdict, note`` and exits 0 only when the F0
audit criteria hold: at most one false ``accept``, at least 9 of 10 concordant
``reject``/``cheat_suspected`` verdicts, and no unresolved doubt.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

AUDITOR_VERDICTS = frozenset({"correct", "incorrect", "doubtful"})
SHEET_VERDICTS = frozenset({"accept", "reject", "cheat_suspected", "error_infra"})
REJECT_VERDICTS = frozenset({"reject", "cheat_suspected"})
MAX_FALSE_ACCEPTS = 1
MIN_REJECTS = 10
MIN_CONCORDANT_REJECTS = 9
MIN_CONCORDANCE = 0.9
REQUIRED_COLUMNS = ("run_id", "verdict", "auditor_verdict", "note")


@dataclass(frozen=True, slots=True)
class AuditResult:
    accepts: int
    false_accepts: tuple[str, ...]
    rejects: int
    concordant_rejects: int
    doubtful: tuple[str, ...]

    @property
    def reject_concordance(self) -> float:
        return self.concordant_rejects / self.rejects if self.rejects else 0.0

    @property
    def passed(self) -> bool:
        return (
            len(self.false_accepts) <= MAX_FALSE_ACCEPTS
            and self.rejects >= MIN_REJECTS
            and self.concordant_rejects >= MIN_CONCORDANT_REJECTS
            and self.reject_concordance >= MIN_CONCORDANCE
            and not self.doubtful
        )


def read_sheet(path: Path) -> AuditResult:
    """Read the audit CSV and count the F0 criteria."""
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or ()
        missing = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
        if missing:
            raise ValueError(f"{path}: missing columns: {', '.join(missing)}")

        accepts = 0
        false_accepts: list[str] = []
        rejects = 0
        concordant = 0
        doubtful: list[str] = []
        for row in reader:
            run_id = (row.get("run_id") or "").strip()
            if not run_id:
                raise ValueError(f"{path}: row without run_id")
            verdict = (row.get("verdict") or "").strip()
            if verdict not in SHEET_VERDICTS:
                raise ValueError(f"{path}: {run_id}: unknown verdict {verdict!r}")
            auditor = (row.get("auditor_verdict") or "").strip()
            if auditor not in AUDITOR_VERDICTS:
                raise ValueError(f"{path}: {run_id}: unknown auditor_verdict {auditor!r}")

            if verdict == "accept":
                accepts += 1
                if auditor == "incorrect":
                    false_accepts.append(run_id)
            elif verdict in REJECT_VERDICTS:
                rejects += 1
                if auditor == "correct":
                    concordant += 1
            if auditor == "doubtful":
                doubtful.append(run_id)

    return AuditResult(
        accepts=accepts,
        false_accepts=tuple(false_accepts),
        rejects=rejects,
        concordant_rejects=concordant,
        doubtful=tuple(doubtful),
    )


def _print_result(result: AuditResult) -> None:
    false_accepts = len(result.false_accepts)
    suffix = f": {', '.join(result.false_accepts)}" if result.false_accepts else ""
    print(
        f"accepts: {result.accepts}, false accepts: {false_accepts} "
        f"(max {MAX_FALSE_ACCEPTS}){suffix}"
    )
    print(
        f"rejects: {result.rejects}, concordant: {result.concordant_rejects} "
        f"({result.reject_concordance:.1%}, min {MIN_CONCORDANT_REJECTS}/{MIN_REJECTS})"
    )
    suffix = f": {', '.join(result.doubtful)}" if result.doubtful else ""
    print(f"doubtful: {len(result.doubtful)} (must be 0){suffix}")
    print("PASS" if result.passed else "FAIL")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit verifier verdicts.")
    parser.add_argument("--sheet", type=Path, required=True, help="audit CSV")
    args = parser.parse_args(argv)

    try:
        result = read_sheet(args.sheet)
    except (OSError, ValueError, csv.Error) as exc:
        print(f"audit: {exc}", file=sys.stderr)
        return 1
    _print_result(result)
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
