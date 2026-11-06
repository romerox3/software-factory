"""M7a and M7b must follow lizard on small hand-written trees and diffs."""

from pathlib import Path

import pytest

from factory.metrics.maintainability import measure, parse_diff

BASE = """def check(x):
    if x:
        return 1
    return 0
"""

ADD_IF = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,4 +1,6 @@
 def check(x):
     if x:
         return 1
+    if x > 10:
+        return 2
     return 0
"""


def _write(root: Path, path: str, text: str) -> None:
    full = root / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(text, encoding="utf-8")


def test_parse_diff_maps_lines_to_both_sides() -> None:
    changes = parse_diff(ADD_IF)

    assert len(changes) == 1
    assert changes[0].path == "app.py"
    assert changes[0].added == frozenset({4, 5})
    assert changes[0].deleted == frozenset()


def test_added_branch_raises_max_complexity_by_one(tmp_path: Path) -> None:
    _write(tmp_path, "app.py", BASE)

    delta = measure(tmp_path, ADD_IF.encode("utf-8"))

    assert delta.ccn_max == 1
    assert delta.ccn_mean == pytest.approx(1.0)
    assert delta.nloc == 2


def test_test_only_diff_has_no_delta(tmp_path: Path) -> None:
    _write(tmp_path, "app.py", BASE)
    _write(tmp_path, "tests/test_app.py", "def test_it():\n    pass\n")
    diff = """diff --git a/tests/test_app.py b/tests/test_app.py
--- a/tests/test_app.py
+++ b/tests/test_app.py
@@ -1,2 +1,3 @@
 def test_it():
+    assert True
     pass
"""

    delta = measure(tmp_path, diff)

    assert delta.ccn_max == 0
    assert delta.ccn_mean == 0.0
    assert delta.nloc == 0
    assert delta.new_dup_blocks == 0


def test_new_function_counts_with_before_zero(tmp_path: Path) -> None:
    _write(tmp_path, "app.py", "def existing(x):\n    return x\n")
    diff = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,2 +1,7 @@
 def existing(x):
     return x
+
+def added(x):
+    if x:
+        return 1
+    return 0
"""

    delta = measure(tmp_path, diff)

    assert delta.ccn_max == 2
    assert delta.ccn_mean == pytest.approx(2.0)
    assert delta.nloc == 4


def test_copied_block_adds_one_duplicate(tmp_path: Path) -> None:
    block = (
        "    alpha = x + 100\n"
        "    beta = alpha * 2\n"
        "    gamma = beta - 7\n"
        "    delta = gamma / 3\n"
        "    epsilon = delta + alpha\n"
        "    zeta = epsilon * beta\n"
        "    eta = zeta - gamma\n"
        "    theta = eta + delta\n"
        "    iota = theta * theta\n"
        "    kappa = iota + epsilon\n"
        "    lam = kappa - beta\n"
        "    mu = lam / 5\n"
        "    nu = mu + gamma\n"
        "    xi = nu * delta\n"
        "    omicron = xi - theta\n"
        "    pi = omicron + iota\n"
        "    rho = pi * kappa\n"
        "    sigma = rho - lam\n"
    )
    body = block.splitlines()
    tail = "    return sigma\n"
    _write(tmp_path, "app.py", "def original(x):\n" + block + tail)
    old_count = len(body) + 2
    added = ["", "", "def copy(x):", *body, "    return sigma"]
    diff = (
        "\n".join(
            [
                "diff --git a/app.py b/app.py",
                "--- a/app.py",
                "+++ b/app.py",
                f"@@ -1,{old_count} +1,{old_count + len(added)} @@",
                " def original(x):",
                *(f" {line}" for line in body),
                "     return sigma",
                *(f"+{line}" for line in added),
            ]
        )
        + "\n"
    )

    delta = measure(tmp_path, diff)

    assert delta.new_dup_blocks >= 1


def test_short_repeated_snippet_is_not_a_duplicate(tmp_path: Path) -> None:
    block = (
        "    alpha, beta = beta, alpha\n"
        "    gamma = alpha + beta + alpha * beta - 100\n"
        "    return gamma if gamma else alpha\n"
    )
    body = ["    first = 1", *block.splitlines(), "    return first"]
    _write(tmp_path, "app.py", "def one(x):\n" + "".join(f"{line}\n" for line in body))
    added = ["", "def two(x):", *body]
    diff = (
        "\n".join(
            [
                "diff --git a/app.py b/app.py",
                "--- a/app.py",
                "+++ b/app.py",
                f"@@ -1,{len(body) + 1} +1,{len(body) + 1 + len(added)} @@",
                " def one(x):",
                *(f" {line}" for line in body),
                *(f"+{line}" for line in added),
            ]
        )
        + "\n"
    )

    assert measure(tmp_path, diff).new_dup_blocks == 0


def test_diff_without_duplication_has_no_new_blocks(tmp_path: Path) -> None:
    _write(tmp_path, "app.py", BASE)

    assert measure(tmp_path, ADD_IF).new_dup_blocks == 0


def test_diff_that_does_not_apply_raises(tmp_path: Path) -> None:
    _write(tmp_path, "app.py", BASE)
    diff = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,1 +1,1 @@
-def missing(x):
+def present(x):
"""

    with pytest.raises(ValueError, match="does not apply"):
        measure(tmp_path, diff)
