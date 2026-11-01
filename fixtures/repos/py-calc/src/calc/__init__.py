"""Tiny calculator used as a fixture repository."""

from __future__ import annotations


def add(a: float, b: float) -> float:
    return a + b


def divide(a: float, b: float) -> float:
    if b == 0:
        raise ZeroDivisionError("division by zero")
    return a / b


def round_half_up(x: float, ndigits: int = 0) -> float:
    """Round ``x`` to ``ndigits`` decimals, with ties rounded away from zero."""
    return round(x, ndigits)
