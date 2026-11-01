"""Test runners that return JUnit statuses keyed by test id.

Every runner runs the verifier's test command inside a checkout, then reads the
JUnit XML with :func:`factory.junit.parse_junit`. Pytest reports module paths
with dots (``tests.test_calc::test_x``); the statuses are normalized to pytest
node ids (``tests/test_calc.py::test_x``) so they match F2P/P2P lists.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Protocol

from factory.junit import Status, parse_junit

DOCKER_WORKDIR = "/workspace"


class RunnerError(RuntimeError):
    """The runner could not execute the command or read its report."""


class TestRunner(Protocol):
    """Anything that can run a verifier's test command on a checkout."""

    def run(
        self,
        repo_dir: Path,
        test_command: str,
        junit_path: str,
        timeout_sec: int,
    ) -> dict[str, Status]:
        """Run the tests and return ``{test_id: status}``."""
        ...


class LocalRunner:
    """Run the test command as a local subprocess."""

    def run(
        self,
        repo_dir: Path,
        test_command: str,
        junit_path: str,
        timeout_sec: int,
    ) -> dict[str, Status]:
        repo_dir = Path(repo_dir)
        report = _resolve_report(repo_dir, junit_path)
        _remove_stale_report(report)
        try:
            subprocess.run(
                ["bash", "-c", test_command],
                cwd=repo_dir,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
        except subprocess.TimeoutExpired as exc:
            raise RunnerError(f"test command timed out after {timeout_sec}s") from exc
        except OSError as exc:
            raise RunnerError(f"could not run test command: {exc}") from exc
        return _read_report(report, repo_dir)


class DockerRunner:
    """Run the test command in a network-less container with the repo mounted."""

    def __init__(self, image: str) -> None:
        self.image = image

    def run(
        self,
        repo_dir: Path,
        test_command: str,
        junit_path: str,
        timeout_sec: int,
    ) -> dict[str, Status]:
        repo_dir = Path(repo_dir).resolve()
        report = _resolve_report(repo_dir, junit_path)
        _remove_stale_report(report)
        command = docker_command(self.image, repo_dir, test_command)
        try:
            subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
        except subprocess.TimeoutExpired as exc:
            raise RunnerError(f"docker run timed out after {timeout_sec}s") from exc
        except OSError as exc:
            raise RunnerError(f"could not run docker: {exc}") from exc
        return _read_report(report, repo_dir)


def docker_command(image: str, repo_dir: Path, test_command: str) -> list[str]:
    """Build the isolated ``docker run`` invocation for ``test_command``."""
    repo_dir = Path(repo_dir).resolve()
    return [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "-v",
        f"{repo_dir}:{DOCKER_WORKDIR}",
        "-w",
        DOCKER_WORKDIR,
        image,
        "bash",
        "-c",
        test_command,
    ]


def docker_available() -> bool:
    """Whether a usable ``docker`` binary is on ``PATH``."""
    return shutil.which("docker") is not None


def _resolve_report(repo_dir: Path, junit_path: str) -> Path:
    report = Path(junit_path)
    if report.is_absolute():
        return report
    return Path(repo_dir) / report


def _remove_stale_report(report: Path) -> None:
    if report.is_file():
        report.unlink()


def _read_report(report: Path, repo_dir: Path) -> dict[str, Status]:
    if not report.is_file():
        raise RunnerError(f"test command produced no JUnit report at {report}")
    try:
        statuses = parse_junit(report)
    except (OSError, ValueError) as exc:
        raise RunnerError(f"could not parse JUnit report at {report}: {exc}") from exc
    return {_pytest_node_id(test_id, repo_dir): status for test_id, status in statuses.items()}


def _pytest_node_id(test_id: str, repo_dir: Path) -> str:
    """Turn pytest's dotted classname into a pytest node id when it maps to a file."""
    prefix, separator, rest = test_id.partition("::")
    repo_dir = Path(repo_dir)
    if (repo_dir / prefix).is_file():
        return test_id
    parts = prefix.split(".")
    for index in range(len(parts), 0, -1):
        candidate = repo_dir.joinpath(*parts[:index]).with_suffix(".py")
        if candidate.is_file():
            tail = parts[index:] + ([rest] if separator else [])
            relative = candidate.relative_to(repo_dir).as_posix()
            return "::".join([relative, *tail])
    return test_id
