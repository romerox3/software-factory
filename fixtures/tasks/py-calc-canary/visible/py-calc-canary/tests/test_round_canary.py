"""Visible rounding checks shipped with the task."""

from calc import round_half_up


def test_visible_rounds_half_up() -> None:
    assert round_half_up(2.5) == 2
