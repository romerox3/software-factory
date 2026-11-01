"""Tests for the local and Docker test runners."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

import pytest

from factory.miner import runner as runner_module
from factory.miner.runner import (
    DockerRunner,
    LocalRunner,
    RunnerError,
    docker_command,
    docker_fixup_command,
    remove_tree,
)

PYTEST = "python -m pytest -q tests/test_ok.py --junitxml=junit.xml -p no:cacheprovider"
REPORT = '<testsuite><testcase classname="tests.test_ok" name="test_ok" /></testsuite>'


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
        (repo / "junit.xml").write_text(REPORT, encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(runner_module.subprocess, "run", fake_run)

    statuses = DockerRunner("python:3.12-slim").run(repo, PYTEST, "junit.xml", 60)

    assert captured == [
        docker_command("python:3.12-slim", repo, PYTEST),
        docker_fixup_command("python:3.12-slim", repo),
    ]
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


def test_docker_command_disables_bytecode(tmp_path: Path) -> None:
    command = docker_command("python:3.12-slim", make_repo(tmp_path), PYTEST)

    assert command[command.index("-e") + 1] == "PYTHONDONTWRITEBYTECODE=1"


def test_docker_fixup_command_chowns_the_mounts(tmp_path: Path) -> None:
    repo = make_repo(tmp_path).resolve()
    logs = (tmp_path / "logs").resolve()

    command = docker_fixup_command("python:3.12-slim", repo, workdir="/testbed", logs_dir=logs)

    assert command[:7] == [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "-v",
        f"{repo}:/testbed",
    ]
    assert _mounts(command) == {"/testbed": repo, "/logs/verifier": logs}
    assert command[command.index("chown") :] == [
        "chown",
        "-R",
        f"{os.getuid()}:{os.getgid()}",
        "/testbed",
        "/logs/verifier",
    ]


def test_docker_runner_restores_ownership_after_a_failed_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repo(tmp_path).resolve()
    captured: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.append(command)
        if "chown" in command:
            return subprocess.CompletedProcess(command, 0)
        (repo / "junit.xml").write_text(REPORT, encoding="utf-8")
        return subprocess.CompletedProcess(command, 1)

    monkeypatch.setattr(runner_module.subprocess, "run", fake_run)

    statuses = DockerRunner("python:3.12-slim").run(repo, PYTEST, "junit.xml", 60)

    assert statuses == {"tests/test_ok.py::test_ok": "passed"}
    assert captured[1] == docker_fixup_command("python:3.12-slim", repo)


def test_docker_runner_restores_ownership_after_a_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repo(tmp_path).resolve()
    captured: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.append(command)
        if "chown" in command:
            return subprocess.CompletedProcess(command, 0)
        raise subprocess.TimeoutExpired(command, 1)

    monkeypatch.setattr(runner_module.subprocess, "run", fake_run)

    with pytest.raises(RunnerError, match="timed out"):
        DockerRunner("python:3.12-slim").run(repo, "sleep 5", "junit.xml", 1)

    assert captured[1] == docker_fixup_command("python:3.12-slim", repo)


def test_docker_runner_logs_a_failed_fixup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    repo = make_repo(tmp_path).resolve()

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if "chown" in command:
            return subprocess.CompletedProcess(command, 1, "", "chown: Operation not permitted")
        (repo / "junit.xml").write_text(REPORT, encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(runner_module.subprocess, "run", fake_run)

    with caplog.at_level(logging.WARNING, logger=runner_module.__name__):
        statuses = DockerRunner("python:3.12-slim").run(repo, PYTEST, "junit.xml", 60)

    assert statuses == {"tests/test_ok.py::test_ok": "passed"}
    assert "chown: Operation not permitted" in caplog.text


def test_docker_runner_keeps_its_scratch_dir_under_the_given_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repo(tmp_path).resolve()
    scratch = tmp_path / "scratch"
    captured: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.append(command)
        if "chown" in command:
            return subprocess.CompletedProcess(command, 0)
        logs = _mounts(command)["/logs/verifier"]
        (logs / "junit.xml").write_text(REPORT, encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(runner_module.subprocess, "run", fake_run)

    statuses = DockerRunner("python:3.12-slim", tmp_root=scratch).run(
        repo,
        PYTEST.replace("junit.xml", "/logs/verifier/junit.xml"),
        "/logs/verifier/junit.xml",
        60,
    )

    assert statuses == {"tests/test_ok.py::test_ok": "passed"}
    logs = _mounts(captured[0])["/logs/verifier"]
    assert logs.parent == scratch.resolve()
    assert logs.name.startswith("factory-junit-")
    assert list(scratch.iterdir()) == []


def test_remove_tree_raises_when_the_cleanup_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_rmtree(_path: Path) -> None:
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(runner_module.shutil, "rmtree", broken_rmtree)

    with pytest.raises(RunnerError, match="could not remove the run directory"):
        remove_tree(tmp_path / "run")


def test_docker_runner_mounts_a_write_dir_for_an_absolute_junit_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repo(tmp_path).resolve()
    captured: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.append(command)
        logs = _mounts(command)["/logs/verifier"]
        (logs / "junit.xml").write_text(REPORT, encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(runner_module.subprocess, "run", fake_run)

    statuses = DockerRunner("python:3.12-slim").run(
        repo,
        PYTEST.replace("junit.xml", "/logs/verifier/junit.xml"),
        "/logs/verifier/junit.xml",
        60,
    )

    assert statuses == {"tests/test_ok.py::test_ok": "passed"}
    assert captured[0][captured[0].index("-w") + 1] == "/workspace"
    assert "/logs/verifier" in _mounts(captured[0])


def test_docker_runner_mounts_the_workspace_at_the_task_workdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repo(tmp_path).resolve()
    captured: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.append(command)
        (repo / "junit.xml").write_text(REPORT, encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(runner_module.subprocess, "run", fake_run)

    statuses = DockerRunner("python:3.12-slim").run(
        repo, PYTEST, "junit.xml", 60, workdir="/testbed"
    )

    assert statuses == {"tests/test_ok.py::test_ok": "passed"}
    assert _mounts(captured[0])["/testbed"] == repo
    assert captured[0][captured[0].index("-w") + 1] == "/testbed"


def _mounts(command: list[str]) -> dict[str, Path]:
    mounts = [command[index + 1] for index, arg in enumerate(command) if arg == "-v"]
    pairs = (mount.rsplit(":", 1) for mount in mounts)
    return {container: Path(host) for host, container in pairs}
