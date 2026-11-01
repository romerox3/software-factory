"""List prices per gateway model alias and the gateway cost reconciliation.

Values are USD per token. The reconciliation compares the gateway's reported
spend with ``tokens x list price``; a deviation over 5 % flags the run. Claude
Code's ``total_cost_usd`` is stored but never used for this check: spike B2
proved it prices cache reads at half the list price, so it always differs by
about 6 % (docs/04 §5.1).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

TOLERANCE = 0.05


@dataclass(frozen=True)
class Price:
    """List price per token for one immutable model behind a gateway alias."""

    input: float
    output: float
    cache_write: float
    cache_read: float


# Sonnet 5.5, the only alias for which docs/04 §5.1/§3 fixes the numbers.
PRICES: Final[dict[str, Price]] = {
    "anthropic-sonnet": Price(
        input=2e-6,
        output=1e-5,
        cache_write=2.5e-6,
        cache_read=2e-7,
    ),
}


@dataclass(frozen=True)
class CostReconciliation:
    """What the price table says versus what the gateway charged."""

    expected_usd: float | None
    actual_usd: float
    deviation: float | None
    flagged: bool


def expected_usd(alias: str, tokens: Mapping[str, Any]) -> float | None:
    """``tokens x list price`` for ``alias``; ``None`` when the alias has no price."""
    price = PRICES.get(alias)
    if price is None:
        return None
    total = 0.0
    for field, rate in (
        ("input", price.input),
        ("output", price.output),
        ("cache_write", price.cache_write),
        ("cache_read", price.cache_read),
    ):
        value = tokens.get(field)
        if value is not None:
            total += int(value) * rate
    return total


def reconcile_cost(
    alias: str, tokens: Mapping[str, Any], usd_real: float, usd_shadow: float
) -> CostReconciliation:
    """Compare the gateway spend (real + shadow) with the list-price expectation."""
    actual = float(usd_real) + float(usd_shadow)
    expected = expected_usd(alias, tokens)
    if expected is None:
        return CostReconciliation(None, actual, None, False)
    if expected == 0.0:
        return CostReconciliation(expected, actual, None, actual > 0.0)
    deviation = actual / expected - 1.0
    return CostReconciliation(expected, actual, deviation, abs(deviation) > TOLERANCE)
