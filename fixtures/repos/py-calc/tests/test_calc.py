"""Visible tests for the toy calculator."""

import pytest
from calc import add, divide, round_half_up


def test_add_integers() -> None:
    assert add(2, 3) == 5


def test_add_floats() -> None:
    assert add(0.1, 0.2) == pytest.approx(0.3)


def test_add_negative() -> None:
    assert add(-4, 1) == -3


def test_divide_integers() -> None:
    assert divide(9, 3) == 3


def test_divide_returns_float() -> None:
    assert divide(1, 2) == 0.5


def test_divide_by_zero_raises() -> None:
    with pytest.raises(ZeroDivisionError):
        divide(1, 0)


def test_round_half_up_below_half() -> None:
    assert round_half_up(0.4) == 0


def test_round_half_up_above_half() -> None:
    assert round_half_up(0.6) == 1


def test_round_half_up_one_digit() -> None:
    assert round_half_up(1.24, 1) == 1.2
