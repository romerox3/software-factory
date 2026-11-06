"""Core metrics must match a hand calculation on the synthetic dataset."""

import json
from pathlib import Path

import pytest

from factory.metrics.core import changed_lines, compute, metrics_for_arm
from factory.metrics.load import load_dataset

DATA = Path(__file__).parent / "data"


def _gold(dataset: str = "basic") -> dict[str, str]:
    path = DATA / dataset / "gold.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_metrics_match_hand_calculation() -> None:
    # Basic dataset, 2 arms x 3 tasks x 3 repetitions.
    # A1 accepts: t1 = 3/3, t2 = 2/3, t3 = 0/3.
    #   pass@1 = (1 + 2/3 + 0) / 3 = 5/9
    #   pass^3 = 1/3 (only t1 has 3 of 3)
    #   M1.gen costs = 3*0.10 + (0.20+0.30+0.40) + 3*0.05 = 1.35 over 5 accepts
    #     = 0.27
    #   M1.total = (1.35 + 9*0.01) / 5 = 1.44 / 5 = 0.288
    #   M7c ratios among accepts: 10/10, 10/10, 10/10, 4/8, 16/8
    #     -> sorted 0.5, 1, 1, 1, 2 -> median 1
    # A2 accepts: t1 = 1/3, t2 = 0/3, t3 = 0/3.
    #   pass@1 = (1/3) / 3 = 1/9
    #   pass^3 = 0
    #   M1.gen costs = (0.20+0.30+0.40) + 3*0.10 + 3*0.10 = 1.50 over 1 accept
    #     = 1.50
    #   M1.total = (1.50 + 9*0.02) / 1 = 1.68
    #   M7c = 12/10 = 1.2
    metrics = compute(load_dataset(DATA / "basic"), gold=_gold())

    a1 = metrics["A1"]
    assert a1.pass_at_1 == pytest.approx(5 / 9)
    assert a1.pass_pow_k == pytest.approx(1 / 3)
    assert a1.m1_gen == pytest.approx(0.27)
    assert a1.m1_total == pytest.approx(0.288)
    assert a1.m7a is None
    assert a1.m7b is None
    assert a1.m7c == pytest.approx(1.0)
    assert a1.tasks == 3
    assert a1.error_infra == 0

    a2 = metrics["A2"]
    assert a2.pass_at_1 == pytest.approx(1 / 9)
    assert a2.pass_pow_k == 0.0
    assert a2.m1_gen == pytest.approx(1.50)
    assert a2.m1_total == pytest.approx(1.68)
    assert a2.m7a is None
    assert a2.m7b is None
    assert a2.m7c == pytest.approx(1.2)
    assert a2.tasks == 3
    assert a2.error_infra == 0

    assert a1.per_task == {"t1": pytest.approx(1.0), "t2": pytest.approx(2 / 3), "t3": 0.0}


def test_error_infra_does_not_count_for_pass1_or_m1() -> None:
    dataset = load_dataset(DATA / "infra")
    metrics = compute(dataset, gold=_gold("infra"))
    a1 = metrics["A1"]

    # Two accepted, non-infra runs survive; the 0.50 infra run is excluded.
    assert a1.pass_at_1 == pytest.approx(2 / 3)
    assert a1.pass_pow_k == 0.0
    assert a1.m1_gen == pytest.approx(0.20)
    assert a1.m1_total == pytest.approx(0.21)
    assert a1.error_infra == 1


def test_no_accept_gives_none_costs() -> None:
    dataset = load_dataset(DATA / "basic")
    rejected = [r for r in dataset.records if r.arm == "A1" and r.task_id == "t3"]

    metrics = metrics_for_arm(rejected)

    assert metrics.pass_at_1 == 0.0
    assert metrics.pass_pow_k == 0.0
    assert metrics.m1_gen is None
    assert metrics.m1_total is None
    assert metrics.m7a is None


def test_changed_lines_ignores_file_headers() -> None:
    diff = (
        "diff --git a/src/app.py b/src/app.py\n"
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-old line\n"
        "+new line\n"
        " context\n"
        "\\ No newline at end of file\n"
    )

    assert changed_lines(diff) == 2
