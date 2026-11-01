"""Helpers shared by the verifier tests: mirrors, task stores, the test image, fake sandboxes."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from factory.verifier.sandbox import RunRequest, RunResult

REPO_ROOT = Path(__file__).parents[2]
FIXTURES = REPO_ROOT / "fixtures"
TRAPS = FIXTURES / "traps"
REPOS = FIXTURES / "repos"
TASKS = FIXTURES / "tasks"

# python:3.12-slim, index digest already present on the development machine and the tower.
BASE_IMAGE = (
    "python:3.12-slim@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9"
)
PYTEST_VERSION = "9.2.0"  # same as uv.lock
DOCKERFILE = f"FROM {BASE_IMAGE}\nRUN pip install --no-cache-dir pytest=={PYTEST_VERSION}\n"
BUILD_TIMEOUT_S = 600

GIT_IDENTITY = [
    "-c",
    "user.name=fixture",
    "-c",
    "user.email=fixture@example.invalid",
    "-c",
    "commit.gpgsign=false",
]


def docker(
    *args: str, stdin: str | None = None, timeout: int = 120
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def ensure_image() -> str:
    """Build (once) and return the id of the test image: BASE_IMAGE plus a pinned pytest."""
    tag = "factory-verifier-test:" + hashlib.sha256(DOCKERFILE.encode()).hexdigest()[:12]
    inspected = docker("image", "inspect", "--format", "{{.Id}}", tag)
    if inspected.returncode != 0:
        built = docker("build", "-q", "-t", tag, "-", stdin=DOCKERFILE, timeout=BUILD_TIMEOUT_S)
        assert built.returncode == 0, f"cannot build the test image: {built.stderr}"
        inspected = docker("image", "inspect", "--format", "{{.Id}}", tag)
    assert inspected.returncode == 0, inspected.stderr
    return inspected.stdout.strip()


def make_mirror(repo_name: str, dest: Path) -> tuple[Path, str]:
    """A git repository with one commit holding ``fixtures/repos/<repo_name>``."""
    shutil.copytree(REPOS / repo_name, dest)
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}

    def git(*args: str) -> str:
        done = subprocess.run(
            ["git", *GIT_IDENTITY, *args],
            cwd=dest,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        return done.stdout.strip()

    git("init", "-q", "-b", "main")
    git("add", "-A", "-f")
    git("commit", "-q", "-m", "base")
    return dest, git("rev-parse", "HEAD")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def copy_store(task_id: str, dest: Path) -> Path:
    """A writable copy of ``fixtures/tasks/<task_id>`` to tweak per test."""
    shutil.copytree(TASKS / task_id, dest)
    return dest


def edit_verifier(store: Path, task_id: str, **changes: Any) -> None:
    path = store / "hidden" / task_id / "verifier.json"
    document = load_json(path)
    document.update(changes)
    path.write_text(json.dumps(document), encoding="utf-8")


def make_ts_store(dest: Path) -> Path:
    """A minimal task store for ``fixtures/repos/ts-calc`` (the fixtures ship no ts task)."""
    task_id = "ts-calc-task"
    visible = dest / "visible" / task_id
    hidden = dest / "hidden" / task_id
    visible.mkdir(parents=True)
    hidden.mkdir(parents=True)
    (visible / "factory.task.json").write_text(
        json.dumps(
            {
                "schema_version": "1",
                "task_id": task_id,
                "class": "C1",
                "data_class": "public",
                "repo": {"commit": "0" * 40},
                "image": "node@sha256:" + "0" * 64,
                "visible_tests": {"command": "npx jest", "ids": []},
                "budget": {"usd": 1.0, "max_turns": 20, "timeout_sec": 300},
            }
        ),
        encoding="utf-8",
    )
    (hidden / "verifier.json").write_text(
        json.dumps(
            {
                "schema_version": "1",
                "task_id": task_id,
                "test_command": "npx jest --reporters=jest-junit /logs/verifier/junit.xml",
                "framework": "jest",
                "junit_path": "/logs/verifier/junit.xml",
                "timeout_sec": 120,
                "diff_guard": {"forbidden_globs": ["src/**/*.test.ts", "jest.config.*"]},
                "mutation": {"enabled": False},
            }
        ),
        encoding="utf-8",
    )
    new_test = "+test('extra', () => {});\n"
    patch = (
        "diff --git a/src/extra.test.ts b/src/extra.test.ts\nnew file mode 100644\n"
        "--- /dev/null\n+++ b/src/extra.test.ts\n@@ -0,0 +1 @@\n" + new_test
    )
    (hidden / "test.patch").write_text(patch, encoding="utf-8")
    (hidden / "gold.patch").write_text(patch, encoding="utf-8")
    (hidden / "f2p.json").write_text('["src/extra.test.ts::extra"]', encoding="utf-8")
    (hidden / "p2p.json").write_text("[]", encoding="utf-8")
    return dest


def junit_xml(cases: dict[str, str]) -> str:
    """JUnit for ``{"tests.test_calc::test_x": "passed" | "failed" | "skipped" | "error"}``."""
    rows = []
    for test_id, status in cases.items():
        classname, _, name = test_id.partition("::")
        body = {
            "passed": "",
            "failed": "<failure message='x'/>",
            "error": "<error message='x'/>",
            "skipped": "<skipped/>",
        }[status]
        rows.append(f'<testcase classname="{classname}" name="{name}">{body}</testcase>')
    return "<testsuites><testsuite name='pytest'>" + "".join(rows) + "</testsuite></testsuites>"


class FakeSandbox:
    """Runs ``behavior(request)`` instead of a container, so error paths can be forced."""

    isolated = True

    def __init__(self, behavior: Callable[[RunRequest], RunResult]) -> None:
        self.behavior = behavior
        self.requests: list[RunRequest] = []

    def image_for(self, task_image: str) -> str:
        return "fake@sha256:" + "a" * 64

    def run(self, request: RunRequest) -> RunResult:
        self.requests.append(request)
        return self.behavior(request)


def report_path(request: RunRequest) -> Path:
    """The junit file the verifier asked the command to write, found in the command line."""
    token = next(part for part in request.command.split() if part.startswith("--junitxml="))
    return request.logs_dir / Path(token.split("=", 1)[1]).name
