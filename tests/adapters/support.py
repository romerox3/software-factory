"""Fixture repos and exports shared by the adapter tests (no Docker, no network)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from factory.snapshot import build_snapshot

REPO_ROOT = Path(__file__).parents[2]
FIXTURES = REPO_ROOT / "fixtures"
REPOS = FIXTURES / "repos"
TRAPS = FIXTURES / "traps"
EXAMPLES = REPO_ROOT / "examples" / "executor"

GIT = ["git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid"]
GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def example_inputs() -> list[Path]:
    return sorted(EXAMPLES.glob("*.input.json"))


def make_repo(dest: Path, repo_name: str = "py-calc", *, trap: bool = False) -> tuple[Path, str]:
    """A git repo holding ``fixtures/repos/<repo_name>``, one commit on ``main``."""
    repo = dest / "repo"
    shutil.copytree(REPOS / repo_name, repo)
    if trap:
        patch = TRAPS / "tamper-gitattributes" / "patch.diff"
        subprocess.run(
            ["git", "apply", str(patch)], cwd=repo, env=GIT_ENV, check=True, capture_output=True
        )
    _git(["init", "-q", "-b", "main"], repo)
    _git(["add", "-A", "-f"], repo)
    _git(["commit", "-q", "-m", "base"], repo)
    return repo, _git(["rev-parse", "HEAD"], repo).strip()


def make_snapshot(dest: Path, *, trap: bool = False) -> tuple[Path, str]:
    """A fresh-init snapshot of ``py-calc``; returns its directory and base commit."""
    repo, base = make_repo(dest, trap=trap)
    snapshot = dest / "snapshot"
    commit = build_snapshot(repo, base, snapshot)
    return snapshot, commit


def export_workspace(snapshot: Path, dest: Path) -> Path:
    """The workspace Docker would export: the snapshot tree plus the agent's ``.git``."""
    workspace = dest / "workspace"
    shutil.copytree(snapshot, workspace, symlinks=True)
    return workspace


def set_file(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def append_file(root: Path, relative: str, text: str) -> None:
    path = root / relative
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def _git(args: list[str], cwd: Path) -> str:
    done = subprocess.run(
        [*GIT, *args], cwd=cwd, env=GIT_ENV, capture_output=True, text=True, check=True
    )
    return done.stdout
