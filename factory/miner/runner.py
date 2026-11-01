"""Test runners that return JUnit statuses keyed by test id.

Every runner runs the verifier's test command inside a checkout, then reads the
JUnit XML with :func:`factory.junit.parse_junit`. Pytest reports module paths
with dots (``tests.test_calc::test_x``); the statuses are normalized to pytest
node ids (``tests/test_calc.py::test_x``) so they match F2P/P2P lists.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Protocol

from factory.junit import Status, parse_junit
from factory.tasks.workdir import DEFAULT_WORKDIR
from factory.testids import pytest_node_id

LOGS_MOUNT = "/logs/verifier"

_log = logging.getLogger(__name__)


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
        *,
        workdir: str = DEFAULT_WORKDIR,
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
        *,
        workdir: str = DEFAULT_WORKDIR,
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
        *,
        workdir: str = DEFAULT_WORKDIR,
    ) -> dict[str, Status]:
        repo_dir = Path(repo_dir).resolve()
        report = _resolve_report(repo_dir, junit_path)
        tmp = Path(tempfile.mkdtemp(prefix="factory-junit-"))
        logs_dir = tmp if _under_logs(junit_path) else None
        try:
            if logs_dir is not None:
                report = logs_dir / PurePosixPath(junit_path).name
            _remove_stale_report(report)
            command = docker_command(
                self.image, repo_dir, test_command, workdir=workdir, logs_dir=logs_dir
            )
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
        finally:
            # The container runs as root, so it may have left root-owned files in
            # the bind mounts (``__pycache__``, build outputs). Hand them back to
            # the host user before the directories are removed or reused.
            _restore_ownership(self.image, repo_dir, workdir=workdir, logs_dir=logs_dir)
            remove_tree(tmp)


def docker_command(
    image: str,
    repo_dir: Path,
    test_command: str,
    *,
    workdir: str = DEFAULT_WORKDIR,
    logs_dir: Path | None = None,
) -> list[str]:
    """Build the isolated ``docker run`` invocation for ``test_command``."""
    repo_dir = Path(repo_dir).resolve()
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "-v",
        f"{repo_dir}:{workdir}",
        "-w",
        workdir,
        "-e",
        "PYTHONDONTWRITEBYTECODE=1",
    ]
    if logs_dir is not None:
        command += ["-v", f"{Path(logs_dir).resolve()}:{LOGS_MOUNT}"]
    return [*command, image, "bash", "-c", test_command]


def docker_fixup_command(
    image: str,
    repo_dir: Path,
    *,
    workdir: str = DEFAULT_WORKDIR,
    logs_dir: Path | None = None,
) -> list[str]:
    """Build the container that hands the mounts back to the host user."""
    repo_dir = Path(repo_dir).resolve()
    owner = f"{os.getuid()}:{os.getgid()}"
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "-v",
        f"{repo_dir}:{workdir}",
    ]
    targets = [workdir]
    if logs_dir is not None:
        command += ["-v", f"{Path(logs_dir).resolve()}:{LOGS_MOUNT}"]
        targets.append(LOGS_MOUNT)
    return [*command, image, "chown", "-R", owner, *targets]


def remove_tree(path: Path) -> None:
    """Delete a run directory, reporting the removal the fix-up could not enable."""
    try:
        shutil.rmtree(path)
    except OSError as exc:
        _log.error("could not remove the run directory %s: %s", path, exc)
        raise RunnerError(f"could not remove the run directory {path}: {exc}") from exc


def docker_available() -> bool:
    """Whether a usable ``docker`` binary is on ``PATH``."""
    return shutil.which("docker") is not None


def _restore_ownership(image: str, repo_dir: Path, *, workdir: str, logs_dir: Path | None) -> None:
    command = docker_fixup_command(image, repo_dir, workdir=workdir, logs_dir=logs_dir)
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True)
    except OSError as exc:
        _log.warning("could not restore ownership of %s: %s", repo_dir, exc)
        return
    if result.returncode != 0:
        stderr = (result.stderr or "").strip().splitlines()
        _log.warning(
            "could not restore ownership of %s: %s",
            repo_dir,
            stderr[-1] if stderr else f"docker exited with {result.returncode}",
        )


def _resolve_report(repo_dir: Path, junit_path: str) -> Path:
    report = Path(junit_path)
    if report.is_absolute():
        return report
    return Path(repo_dir) / report


def _under_logs(junit_path: str) -> bool:
    return junit_path.startswith(LOGS_MOUNT + "/")


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
    return {pytest_node_id(test_id, repo_dir): status for test_id, status in statuses.items()}
