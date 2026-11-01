"""Basic SZZ for M4: regressions per 100 merged changes (docs/01-metrics.md).

A fix is a commit on the main branch whose message matches the fix regex. SZZ
attributes the bug to the commits that last touched the lines the fix deletes or
modifies, using ``git blame`` on the fix's parent (PyDriller's
``get_commits_last_modified_lines``).

Test files are filtered with the shared path heuristic of docs/06 §2.2 step 3
(``factory.miner.split``), and blank or comment-only lines are ignored by
PyDriller. A change is censored while ``window_days`` have not elapsed since its
commit, so it is left out of the denominator until the window is observable.
"""

from __future__ import annotations

import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydriller import Commit, Git

from factory.miner.split import is_test_path

DEFAULT_FIX_REGEX = r"(?i)\b(fix|fixes|fixed|bug|regression|revert)\b"


def find_fix_commits(
    repo: Path,
    since: datetime,
    until: datetime,
    fix_regex: str = DEFAULT_FIX_REGEX,
) -> list[str]:
    """Return the main-branch commits in ``[since, until]`` matching ``fix_regex``."""
    repo = Path(repo)
    pattern = re.compile(fix_regex)
    since = _as_utc(since)
    until = _as_utc(until)
    git = Git(repo)
    return [
        commit.hash
        for commit in git.get_list_commits(rev=_main_branch(repo))
        if since <= _commit_date(commit) <= until and pattern.search(commit.msg)
    ]


def bug_introducing(repo: Path, fix_sha: str) -> set[str]:
    """Return the commits that introduced the lines ``fix_sha`` deletes or changes."""
    git = Git(Path(repo))
    return _bug_introducing(git, git.get_commit(fix_sha))


def regressions_per_100(
    repo: Path,
    changes: list[str],
    *,
    window_days: int = 90,
    as_of: datetime,
) -> dict[str, int | float]:
    """Measure regressions per 100 evaluated changes, censoring recent changes.

    A change is a regression when it is the bug-introducing commit of a fix whose
    date falls within ``window_days`` after the change, never after ``as_of``.
    Changes younger than ``window_days`` at ``as_of`` are censored: they are
    neither in the denominator nor counted as regressions.
    """
    repo = Path(repo)
    as_of = _as_utc(as_of)
    window = timedelta(days=window_days)
    unique_changes = list(dict.fromkeys(changes))
    if not unique_changes:
        return {"evaluated": 0, "censored": 0, "regressions": 0, "per_100": 0.0}

    git = Git(repo)
    change_dates = {sha: _commit_date(git.get_commit(sha)) for sha in unique_changes}
    pattern = re.compile(DEFAULT_FIX_REGEX)
    fixes = [
        commit
        for commit in git.get_list_commits(rev=_main_branch(repo))
        if min(change_dates.values()) <= _commit_date(commit) <= as_of
        and pattern.search(commit.msg)
    ]

    regressions: set[str] = set()
    for fix in fixes:
        fix_date = _commit_date(fix)
        for sha in _bug_introducing(git, fix):
            change_date = change_dates.get(sha)
            if change_date is not None and timedelta(0) <= fix_date - change_date <= window:
                regressions.add(sha)

    censored = {sha for sha, date in change_dates.items() if as_of - date < window}
    evaluated = [sha for sha in unique_changes if sha not in censored]
    counted = sum(1 for sha in evaluated if sha in regressions)
    per_100 = 100.0 * counted / len(evaluated) if evaluated else 0.0
    return {
        "evaluated": len(evaluated),
        "censored": len(unique_changes) - len(evaluated),
        "regressions": counted,
        "per_100": per_100,
    }


def _bug_introducing(git: Git, commit: Commit) -> set[str]:
    introduced: set[str] = set()
    for modification in commit.modified_files:
        path = modification.old_path or modification.new_path
        if path is None or is_test_path(path):
            continue
        blamed = git.get_commits_last_modified_lines(commit, modification=modification)
        for shas in blamed.values():
            introduced.update(shas)
    return introduced


def _main_branch(repo: Path) -> str:
    for branch in ("main", "master"):
        result = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            cwd=repo,
            check=False,
            capture_output=True,
        )
        if result.returncode == 0:
            return branch
    return "HEAD"


def _commit_date(commit: Commit) -> datetime:
    return commit.committer_date.astimezone(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
