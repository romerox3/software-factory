"""Paired bootstrap confidence intervals and the non-inferiority rule."""

from __future__ import annotations

import random
from collections.abc import Mapping


def paired_bootstrap(
    a: Mapping[str, float],
    b: Mapping[str, float],
    *,
    n: int = 10000,
    seed: int,
) -> tuple[float, float, float]:
    """Return the mean difference A - B and its 95 % percentile interval.

    Only tasks present in both mappings are resampled, with replacement, using
    ``random.Random(seed)`` so the same input and seed always give the same
    interval.
    """
    if n < 1:
        raise ValueError("n must be >= 1")
    common = sorted(set(a) & set(b))
    if not common:
        raise ValueError("the arms share no tasks")
    differences = [a[task] - b[task] for task in common]
    size = len(differences)
    point = sum(differences) / size

    rng = random.Random(seed)
    means = [sum(differences[rng.randrange(size)] for _ in range(size)) / size for _ in range(n)]
    means.sort()
    return point, _percentile(means, 0.025), _percentile(means, 0.975)


def non_inferior(lo: float, delta: float) -> bool:
    """The lower bound of the paired interval must stay above -delta."""
    return lo > -delta


def _percentile(ordered: list[float], q: float) -> float:
    position = q * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight
