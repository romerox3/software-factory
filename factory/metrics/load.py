"""Join executor runs with verifier verdicts into metric records.

``runs/*.json`` follows ``schemas/executor-output.schema.json``; task, arm,
attempt and repetition come from the matching ``verdicts/*.json`` because the
executor output does not carry them. ``error_infra`` verdicts measure the
harness, not the arm, so they are removed from every calculation and kept
separately for the report.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

VERDICTS = frozenset({"accept", "reject", "cheat_suspected", "error_infra"})
ERROR_INFRA = "error_infra"


@dataclass(frozen=True, slots=True)
class RunRecord:
    """One executor execution joined with its verifier verdict."""

    run_id: str
    task_id: str
    arm: str
    attempt: int
    repetition: int
    verdict: str
    cost_usd: float
    verify_cost_usd: float
    diff_text: str | None

    @property
    def accepted(self) -> bool:
        return self.verdict == "accept"


@dataclass(frozen=True, slots=True)
class Dataset:
    """Usable records plus the ``error_infra`` runs excluded from metrics."""

    records: tuple[RunRecord, ...]
    error_infra: tuple[RunRecord, ...] = ()

    def error_infra_count(self, arm: str) -> int:
        return sum(record.arm == arm for record in self.error_infra)


def load_dataset(root: Path) -> Dataset:
    """Load ``<root>/runs/*.json`` and ``<root>/verdicts/*.json`` joined by run id.

    Any run without a verdict, any verdict without a run, and any unknown
    verdict value raises ``ValueError``: silently dropping a record would bias
    every metric.
    """
    runs = _load_json_dir(root / "runs")
    verdicts = _load_json_dir(root / "verdicts")

    missing_verdicts = sorted(set(runs) - set(verdicts))
    if missing_verdicts:
        raise ValueError(f"runs without a verdict: {', '.join(missing_verdicts)}")
    missing_runs = sorted(set(verdicts) - set(runs))
    if missing_runs:
        raise ValueError(f"verdicts without a run: {', '.join(missing_runs)}")

    records: list[RunRecord] = []
    infra: list[RunRecord] = []
    for run_id in sorted(verdicts):
        record = _join(root, runs[run_id], verdicts[run_id])
        if record.verdict == ERROR_INFRA:
            infra.append(record)
        else:
            records.append(record)

    def order(record: RunRecord) -> tuple[str, str, int, int, str]:
        return (
            record.arm,
            record.task_id,
            record.repetition,
            record.attempt,
            record.run_id,
        )

    return Dataset(
        records=tuple(sorted(records, key=order)),
        error_infra=tuple(sorted(infra, key=order)),
    )


def _join(root: Path, run: Mapping[str, Any], verdict: Mapping[str, Any]) -> RunRecord:
    run_id = _string(verdict, "run_id", "verdict")
    if run.get("run_id") != run_id:
        raise ValueError(f"run {run_id}: run_id mismatch with its verdict")

    value = _string(verdict, "verdict", f"verdict {run_id}")
    if value not in VERDICTS:
        raise ValueError(f"verdict {run_id}: unknown verdict {value!r}")

    return RunRecord(
        run_id=run_id,
        task_id=_string(verdict, "task_id", f"verdict {run_id}"),
        arm=_string(verdict, "arm", f"verdict {run_id}"),
        attempt=_int(verdict, "attempt", f"verdict {run_id}"),
        repetition=_int(verdict, "repetition", f"verdict {run_id}"),
        verdict=value,
        cost_usd=_cost(run, run_id),
        verify_cost_usd=_number(verdict, "verify_cost_usd", f"verdict {run_id}"),
        diff_text=_diff_text(root, run, run_id),
    )


def _cost(run: Mapping[str, Any], run_id: str) -> float:
    cost = run.get("cost")
    if not isinstance(cost, dict):
        raise TypeError(f"run {run_id}: missing cost object")
    return _number(cost, "usd_real", f"run {run_id}") + _number(cost, "usd_shadow", f"run {run_id}")


def _diff_text(root: Path, run: Mapping[str, Any], run_id: str) -> str | None:
    diff = run.get("diff")
    if not isinstance(diff, dict):
        raise TypeError(f"run {run_id}: missing diff object")
    uri = diff.get("uri")
    if not isinstance(uri, str) or not uri:
        return None
    path = Path(uri)
    if not path.is_absolute():
        path = root / path
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _load_json_dir(directory: Path) -> dict[str, dict[str, Any]]:
    if not directory.is_dir():
        raise ValueError(f"{directory}: not a directory")
    documents: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: invalid JSON") from exc
        if not isinstance(document, dict):
            raise TypeError(f"{path}: expected a JSON object")
        run_id = _string(document, "run_id", str(path))
        if run_id in documents:
            raise ValueError(f"{path}: duplicate run_id {run_id}")
        documents[run_id] = document
    return documents


def _number(source: Mapping[str, Any], key: str, where: str) -> float:
    value = source.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{where}: {key} must be a number")
    if value < 0:
        raise ValueError(f"{where}: {key} must not be negative")
    return float(value)


def _int(source: Mapping[str, Any], key: str, where: str) -> int:
    value = source.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{where}: {key} must be an integer >= 1")
    return value


def _string(source: Mapping[str, Any], key: str, where: str) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{where}: {key} must be a non-empty string")
    return value
