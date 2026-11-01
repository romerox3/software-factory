"""Tests for the code/test diff splitter."""

from __future__ import annotations

from factory.miner.split import split_patch

DIFF = (
    "diff --git a/src/a.py b/src/a.py\n"
    "--- a/src/a.py\n"
    "+++ b/src/a.py\n"
    "@@ -1 +1 @@\n"
    "-x = 1\n"
    "+x = 2\n"
    "diff --git a/tests/test_a.py b/tests/test_a.py\n"
    "--- a/tests/test_a.py\n"
    "+++ b/tests/test_a.py\n"
    "@@ -1 +1 @@\n"
    "-x = 1\n"
    "+x = 2\n"
    "diff --git a/web/a.test.ts b/web/a.test.ts\n"
    "--- a/web/a.test.ts\n"
    "+++ b/web/a.test.ts\n"
    "@@ -1 +1 @@\n"
    "-x = 1\n"
    "+x = 2\n"
)


def test_split_patch_routes_whole_files_by_path() -> None:
    code, tests = split_patch(DIFF)

    assert "diff --git a/src/a.py b/src/a.py" in code
    assert "tests/test_a.py" not in code
    assert "a.test.ts" not in code

    assert "diff --git a/tests/test_a.py b/tests/test_a.py" in tests
    assert "diff --git a/web/a.test.ts b/web/a.test.ts" in tests
    assert "src/a.py" not in tests


def test_split_patch_without_matches_keeps_everything_in_code() -> None:
    code, tests = split_patch(DIFF.split("diff --git a/tests/")[0])

    assert code == DIFF.split("diff --git a/tests/")[0]
    assert tests == ""
