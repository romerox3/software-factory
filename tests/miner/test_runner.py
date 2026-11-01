"""Tests for the local and Docker test runners."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from factory.miner import runner as runner_module
from factory.miner.runner import DockerRunner, LocalRunner, RunnerError, docker_command

PYTEST = "python -m pytest -q tests/test_ok.py --junitxml=junit.xml -p no:cacheprovider"


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_ok.py").write_text(
        "def test_ok() -> None:\n    assert True\n\ndef test_bad() -> None:\n    assert False\n",
        encoding="utf-8",
    )
    return repo


def test_local_runner_returns_pytest_node_ids(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    statuses = LocalRunner().run(repo, PYTEST, "junit.xml", 60)

    assert statuses == {
        "tests/test_ok.py::test_ok": "passed",
        "tests/test_ok.py::test_bad": "failed",
    }


def test_local_runner_raises_on_timeout(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    with pytest.raises(RunnerError, match="timed out"):
        LocalRunner().run(repo, "sleep 5", "junit.xml", 1)


def test_local_runner_raises_without_report(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    with pytest.raises(RunnerError, match="no JUnit report"):
        LocalRunner().run(repo, "true", "junit.xml", 60)


def test_docker_runner_builds_an_isolated_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repo(tmp_path).resolve()
    captured: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.append(command)
        (repo / "junit.xml").write_text(
            '<testsuite><testcase classname="tests.test_ok" name="test_ok" /></testsuite>',
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(runner_module.subprocess, "run", fake_run)

    statuses = DockerRunner("python:3.12-slim").run(repo, PYTEST, "junit.xml", 60)

    assert captured == [docker_command("python:3.12-slim", repo, PYTEST)]
    assert captured[0][:8] == [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "-v",
        f"{repo}:/workspace",
        "-w",
    ]
    assert statuses == {"tests/test_ok.py::test_ok": "passed"}
