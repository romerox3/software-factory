"""Build a fresh-init snapshot of a base commit's tree (threat T15).

The destination repo is a brand new repository with a single root commit, so no
object, ref or remote from the source history can be reached from it.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

COMMIT_MESSAGE = "snapshot"
AUTHOR_NAME = "factory"
AUTHOR_EMAIL = "factory@invalid"
FIXED_DATE = "2000-01-01T00:00:00Z"


def _run_git(args: list[str], cwd: Path, env: dict[str, str] | None = None) -> str:
    command = ["git", *args]
    try:
        result = subprocess.run(
            command, cwd=cwd, env=env, check=True, capture_output=True, text=True
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip() or "(git wrote nothing to stderr)"
        raise RuntimeError(f"{' '.join(command)} failed: {stderr}") from exc
    return result.stdout.strip()


def _dest_env(home: Path) -> dict[str, str]:
    """Environment for git calls on ``dest``: no user or system config, no identity.

    ``dest`` is a throwaway repository, so it must not inherit the developer's
    global hooks, signing keys or identity. ``HOME`` points at an empty directory
    so git cannot pick up anything from the real home either.
    """
    env = os.environ.copy()
    env.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "HOME": str(home),
            "GIT_AUTHOR_NAME": AUTHOR_NAME,
            "GIT_AUTHOR_EMAIL": AUTHOR_EMAIL,
            "GIT_COMMITTER_NAME": AUTHOR_NAME,
            "GIT_COMMITTER_EMAIL": AUTHOR_EMAIL,
            "GIT_AUTHOR_DATE": FIXED_DATE,
            "GIT_COMMITTER_DATE": FIXED_DATE,
        }
    )
    return env


def _prepare_dest(dest: Path) -> None:
    if dest.exists():
        if not dest.is_dir():
            raise ValueError(f"{dest} exists and is not a directory")
        if any(dest.iterdir()):
            raise ValueError(f"{dest} is not empty")
        return
    dest.mkdir(parents=True)


def build_snapshot(source_repo: Path, base: str, dest: Path) -> str:
    """Materialize the tree of ``base`` in ``dest`` as a single-commit repo.

    Returns the sha of the new commit. The source repository's index, HEAD,
    refs and working tree are never touched: the tree is read through a
    temporary index file. ``git archive`` is not used because it honours
    ``export-ignore`` and would drop files.
    """
    source_repo = Path(source_repo)
    dest = Path(dest)
    _prepare_dest(dest)

    with tempfile.TemporaryDirectory(prefix="factory-snapshot-index-") as tmp:
        index_env = os.environ.copy()
        index_env["GIT_INDEX_FILE"] = str(Path(tmp) / "index")
        _run_git(
            ["-c", "core.autocrlf=false", "read-tree", base],
            cwd=source_repo,
            env=index_env,
        )
        _run_git(
            [
                "-c",
                "core.autocrlf=false",
                "checkout-index",
                "-a",
                "-f",
                f"--prefix={dest}/",
            ],
            cwd=source_repo,
            env=index_env,
        )

    with tempfile.TemporaryDirectory(prefix="factory-snapshot-home-") as home:
        env = _dest_env(Path(home))
        _run_git(["init", "-q", "--template=", "-b", "main"], cwd=dest, env=env)
        _run_git(["-c", "core.autocrlf=false", "add", "-A", "-f"], cwd=dest, env=env)
        _run_git(
            [
                "-c",
                "commit.gpgsign=false",
                "commit",
                "-q",
                "--no-verify",
                "--allow-empty",
                "-m",
                COMMIT_MESSAGE,
            ],
            cwd=dest,
            env=env,
        )
        return _run_git(["rev-parse", "HEAD"], cwd=dest, env=env)
