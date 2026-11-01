"""Per-arm F0 metrics: M1 (generation and total), M2 (pass@1, pass^k) and M7a.

The k first repetitions of each task are selected per arm. When a repetition
was retried, only the earliest matching attempt counts, and ``error_infra``
runs never reach this module (see ``factory.metrics.load``).
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from factory.metrics.load import Dataset, RunRecord

DEFAULT_K = 3
BASELINE_ARM = "A1"


@dataclass(frozen=True, slots=True)
class ArmMetrics:
    """Metrics of one arm over its k-first repetitions."""

    pass_at_1: float | None
    pass_pow_k: float | None
    m1_gen: float | None
    m1_total: float | None
    m7a: float | None
    # TODO(F0-18): M7b (new duplicated blocks) needs jscpd and M7c (size vs
    # gold) needs lizard, so both stay None until those tools are wired in.
    m7b: float | None
    m7c: float | None
    tasks: int
    error_infra: int
    per_task: Mapping[str, float] = field(default_factory=dict)


def changed_lines(diff: str) -> int:
    """Count added and removed lines in a unified diff, ignoring file headers."""
    count = 0
    for line in diff.splitlines():
        if line.startswith(("--- ", "+++ ")):
            continue
        if line.startswith(("+", "-")):
            count += 1
    return count


def select_first_k(records: Sequence[RunRecord], k: int) -> list[RunRecord]:
    """Return the lowest k repetitions per task, one attempt per repetition."""
    if k < 1:
        raise ValueError("k must be >= 1")
    by_task: dict[str, dict[int, RunRecord]] = defaultdict(dict)
    for record in records:
        current = by_task[record.task_id].get(record.repetition)
        if current is None or (record.attempt, record.run_id) < (
            current.attempt,
            current.run_id,
        ):
            by_task[record.task_id][record.repetition] = record

    selected: list[RunRecord] = []
    for task_id in sorted(by_task):
        repetitions = by_task[task_id]
        for repetition in sorted(repetitions)[:k]:
            selected.append(repetitions[repetition])
    return selected


def metrics_for_arm(
    records: Sequence[RunRecord],
    *,
    k: int = DEFAULT_K,
    gold: Mapping[str, str] | None = None,
    error_infra: int = 0,
) -> ArmMetrics:
    """Compute an arm's metrics from its non-``error_infra`` records."""
    selected = select_first_k(records, k)
    by_task: dict[str, list[RunRecord]] = defaultdict(list)
    for record in selected:
        by_task[record.task_id].append(record)

    per_task: dict[str, float] = {}
    for task_id, task_records in by_task.items():
        accepted = sum(record.accepted for record in task_records)
        per_task[task_id] = accepted / k

    pass_at_1 = statistics.fmean(per_task.values()) if per_task else None
    consistent = sum(
        1 for task_records in by_task.values() if sum(r.accepted for r in task_records) == k
    )
    pass_pow_k = consistent / len(by_task) if by_task else None

    accepted = sum(record.accepted for record in selected)
    if accepted:
        generation = sum(record.cost_usd for record in selected)
        verification = sum(record.verify_cost_usd for record in selected)
        m1_gen: float | None = generation / accepted
        m1_total: float | None = (generation + verification) / accepted
    else:
        m1_gen = None
        m1_total = None

    return ArmMetrics(
        pass_at_1=pass_at_1,
        pass_pow_k=pass_pow_k,
        m1_gen=m1_gen,
        m1_total=m1_total,
        m7a=_m7a(selected, gold),
        m7b=None,
        m7c=None,
        tasks=len(by_task),
        error_infra=error_infra,
        per_task=per_task,
    )


def compute(
    dataset: Dataset,
    *,
    k: int = DEFAULT_K,
    gold: Mapping[str, str] | None = None,
) -> dict[str, ArmMetrics]:
    """Compute every arm present in the dataset, with A1 first."""
    by_arm: dict[str, list[RunRecord]] = defaultdict(list)
    for record in dataset.records:
        by_arm[record.arm].append(record)

    arms = sorted(by_arm, key=lambda arm: (arm != BASELINE_ARM, arm))
    return {
        arm: metrics_for_arm(
            by_arm[arm],
            k=k,
            gold=gold,
            error_infra=dataset.error_infra_count(arm),
        )
        for arm in arms
    }


def _m7a(selected: Sequence[RunRecord], gold: Mapping[str, str] | None) -> float | None:
    if gold is None:
        return None
    ratios: list[float] = []
    for record in selected:
        if not record.accepted:
            continue
        if record.task_id not in gold:
            raise ValueError(f"gold diff missing for task {record.task_id}")
        if record.diff_text is None:
            raise ValueError(f"diff missing for accepted run {record.run_id}")
        denominator = changed_lines(gold[record.task_id])
        if denominator == 0:
            raise ValueError(f"gold diff changes no lines for task {record.task_id}")
        ratios.append(changed_lines(record.diff_text) / denominator)
    return statistics.median(ratios) if ratios else None
