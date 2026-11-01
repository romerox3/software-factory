"""The paired bootstrap must be reproducible and the rule must be strict."""

from factory.metrics.stats import non_inferior, paired_bootstrap


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
