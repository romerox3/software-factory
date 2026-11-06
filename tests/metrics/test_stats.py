"""The paired bootstrap must be reproducible, the rule strict and the bound exact."""

import pytest

from factory.metrics.stats import clopper_pearson_upper, non_inferior, paired_bootstrap


def test_same_seed_gives_the_same_interval() -> None:
    a = {"t1": 1.0, "t2": 0.0, "t3": 0.5, "t4": 1 / 3}
    b = {"t1": 0.0, "t2": 0.0, "t3": 0.5, "t4": 1 / 3}

    first = paired_bootstrap(a, b, n=1000, seed=7)
    second = paired_bootstrap(a, b, n=1000, seed=7)

    assert first == second
    assert first[1] <= first[0] <= first[2]


def test_identical_arms_have_a_zero_interval() -> None:
    a = {"t1": 1.0, "t2": 0.0, "t3": 0.5}

    diff, lo, hi = paired_bootstrap(a, a, n=1000, seed=7)

    assert diff == 0.0
    assert lo <= 0.0 <= hi


def test_non_inferior_is_strict_at_minus_delta() -> None:
    assert non_inferior(-0.099, 0.1) is True
    assert non_inferior(-0.1, 0.1) is False


def test_zero_cheats_gives_the_rule_of_three() -> None:
    assert clopper_pearson_upper(0, 30) == pytest.approx(1 - 0.05 ** (1 / 30))


def test_upper_bound_matches_known_clopper_pearson_values() -> None:
    # One-sided 95 % upper bounds: scipy.stats.beta.ppf(0.95, x + 1, n - x).
    # The task brief quoted 0.1503 for x=1, n=30, but the one-sided bound is
    # 0.1486; 0.1503 does not match this bound under any usual convention.
    assert clopper_pearson_upper(1, 30) == pytest.approx(0.1486, abs=5e-5)
    assert clopper_pearson_upper(3, 30) == pytest.approx(0.2386, abs=5e-5)


def test_every_trial_cheating_has_an_upper_bound_of_one() -> None:
    assert clopper_pearson_upper(3, 3) == 1.0
