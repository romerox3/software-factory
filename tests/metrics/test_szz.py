"""Tests for the basic SZZ used by M4 (regressions per 100 changes)."""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from factory.metrics.szz import bug_introducing, find_fix_commits, regressions_per_100

GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@invalid",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@invalid",
}
A_DATE = "2024-10-01T00:00:00Z"
B_DATE = "2025-01-02T00:00:00Z"
C_DATE = "2025-01-04T00:00:00Z"


def run_git(repo: Path, *args: str, date: str | None = None) -> str:
    env = dict(GIT_ENV)
    if date is not None:
        env["GIT_AUTHOR_DATE"] = date
        env["GIT_COMMITTER_DATE"] = date
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def commit_all(repo: Path, message: str, date: str) -> str:
    run_git(repo, "add", "-A")
    run_git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", message, date=date)
    return run_git(repo, "rev-parse", "HEAD")


def new_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-q", "-b", "main")
    return repo


def write(repo: Path, path: str, content: str) -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def buggy_history(tmp_path: Path) -> tuple[Path, str, str, str]:
    repo = new_repo(tmp_path)
    write(repo, "src/m.py", "def add(a, b):\n    return a + b\n")
    a = commit_all(repo, "feat: add m", A_DATE)
    write(repo, "src/m.py", "def add(a, b):\n    return a - b\n")
    b = commit_all(repo, "feat: change m", B_DATE)
    write(repo, "src/m.py", "def add(a, b):\n    return a + b\n")
    c = commit_all(repo, "fix: bug in m", C_DATE)
    return repo, a, b, c


def test_find_fix_commits_and_bug_introducing(tmp_path: Path) -> None:
    repo, _a, b, c = buggy_history(tmp_path)

    fixes = find_fix_commits(
        repo, datetime(2024, 12, 1, tzinfo=UTC), datetime(2025, 1, 10, tzinfo=UTC)
    )

    assert fixes == [c]
    assert bug_introducing(repo, c) == {b}


def test_fix_touching_only_a_test_attributes_nothing(tmp_path: Path) -> None:
    repo = new_repo(tmp_path)
    write(repo, "src/m.py", "def add(a, b):\n    return a + b\n")
    write(repo, "tests/test_m.py", "def test_add():\n    assert True\n")
    commit_all(repo, "feat: add m and its test", A_DATE)
    write(repo, "tests/test_m.py", "def test_add():\n    assert 1 == 1\n")
    fix = commit_all(repo, "fix: tighten the test", B_DATE)

    assert bug_introducing(repo, fix) == set()


def test_fix_touching_code_named_like_a_test_still_attributes(tmp_path: Path) -> None:
    repo = new_repo(tmp_path)
    write(repo, "src/contest.py", "SCORE = 10\n")
    commit_all(repo, "feat: add contest scoring", A_DATE)
    write(repo, "src/contest.py", "SCORE = 1\n")
    b = commit_all(repo, "feat: tune contest scoring", B_DATE)
    write(repo, "src/contest.py", "SCORE = 10\n")
    fix = commit_all(repo, "fix: restore contest scoring", C_DATE)

    assert bug_introducing(repo, fix) == {b}


def test_blank_and_comment_lines_are_not_attributed(tmp_path: Path) -> None:
    repo = new_repo(tmp_path)
    write(repo, "src/m.py", "def add(a, b):\n    # keep this comment\n    return a + b\n\n")
    commit_all(repo, "feat: add m", A_DATE)
    write(repo, "src/m.py", "def add(a, b):\n    return a + b\n")
    fix = commit_all(repo, "fix: drop the comment", B_DATE)

    assert bug_introducing(repo, fix) == set()


def test_regressions_per_100_and_censoring(tmp_path: Path) -> None:
    repo, a, b, _c = buggy_history(tmp_path)

    assert regressions_per_100(
        repo, [a, b], window_days=90, as_of=datetime(2025, 7, 21, tzinfo=UTC)
    ) == {
        "evaluated": 2,
        "censored": 0,
        "regressions": 1,
        "per_100": 50.0,
    }

    assert regressions_per_100(
        repo, [a, b], window_days=90, as_of=datetime(2025, 1, 12, tzinfo=UTC)
    ) == {
        "evaluated": 1,
        "censored": 1,
        "regressions": 0,
        "per_100": 0.0,
    }
