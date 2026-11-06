"""Paired bootstrap confidence intervals, the non-inferiority rule and the exact bound."""

from __future__ import annotations

import math
import random
from collections.abc import Mapping

ALPHA = 0.05
TOLERANCE = 1e-9


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


def clopper_pearson_upper(x: int, n: int) -> float:
    """One-sided 95 % Clopper-Pearson upper bound of ``x`` successes in ``n`` trials.

    Solves ``P(X <= x; n, p) = alpha`` by bisection. With zero successes it is
    exactly the rule of three: ``1 - alpha ** (1 / n)``.
    """
    if n < 1 or not 0 <= x <= n:
        raise ValueError("need 0 <= x <= n and n >= 1")
    if x == n:
        return 1.0
    if x == 0:
        return 1.0 - ALPHA ** (1.0 / n)

    low, high = 0.0, 1.0
    while high - low > TOLERANCE:
        middle = (low + high) / 2.0
        if _binomial_cdf(x, n, middle) > ALPHA:
            low = middle
        else:
            high = middle
    return (low + high) / 2.0


def _binomial_cdf(x: int, n: int, p: float) -> float:
    return sum(math.comb(n, k) * p**k * (1.0 - p) ** (n - k) for k in range(x + 1))


def _percentile(ordered: list[float], q: float) -> float:
    position = q * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight
