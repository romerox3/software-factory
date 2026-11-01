"""Sandbox that runs the candidate code: an ephemeral, network-less Docker container.

Only two host directories reach the container: a copy of the checkout (diff and hidden
``test.patch`` already applied) and an empty logs directory. No store, mirror, credential or
environment variable of the host is passed. The verdict is written by the supervisor outside.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Protocol

IMAGE_REF = re.compile(r"^(?:[^@\s]+@sha256:[0-9a-f]{64}|sha256:[0-9a-f]{64})$")
WORKSPACE_MOUNT = "/workspace"
LOGS_MOUNT = "/logs/verifier"
TAIL_BYTES = 2000
# The result stream travels on stdout. A run that prints more than this is not a pytest run we
# can trust: the stream is flagged as truncated and the verifier rejects it.
MAX_STDOUT_BYTES = 64 * 1024 * 1024
# Variables whose value in the image is extended, not replaced, by the request.
PREPEND_VARS = frozenset({"PYTHONPATH"})
# Exit codes docker reserves for its own failures. The wrapper below maps them to 1 when they
# come from the code under test, so that only docker itself can produce them.
DOCKER_FAILURE_CODES = frozenset({125, 126, 127})
WRAPPER = 'sh -c "$1"; ec=$?; case $ec in 125|126|127) ec=1;; esac; exit $ec'


class SandboxError(RuntimeError):
    """The sandbox could not run (docker missing, daemon down, image absent)."""


@dataclass(frozen=True)
class RunRequest:
    image: str
    workspace: Path
    logs_dir: Path
    command: str
    timeout_s: int
    # Container path where the workspace is mounted: the task's ``repo.workdir``.
    workdir: str = WORKSPACE_MOUNT
    # Extra environment (verifier-controlled; ``PYTHONPATH`` is prepended to the image's own).
    env: tuple[tuple[str, str], ...] = ()
    # Host directories mounted read-only at the given container path (verifier-controlled).
    read_only_mounts: tuple[tuple[Path, str], ...] = ()


@dataclass(frozen=True)
class RunResult:
    exit_code: int | None
    timed_out: bool = False
    oom_killed: bool = False
    duration_s: float = 0.0
    stdout_tail: str = ""
    stderr_tail: str = ""
    # The whole stdout (up to MAX_STDOUT_BYTES); the pytest result stream is read from it.
    stdout: bytes = b""
    stdout_truncated: bool = False


class Sandbox(Protocol):
    """Runs one command against a workspace. ``isolated`` must be true for real isolation."""

    isolated: bool

    def image_for(self, task_image: str) -> str: ...

    def run(self, request: RunRequest) -> RunResult: ...


@dataclass
class DockerSandbox:
    """``docker run --rm --network none`` with a read-only root and an unprivileged user."""

    image: str | None = None
    memory_mb: int = 1024
    cpus: float = 2.0
    pids_limit: int = 512
    timeout_cap_s: int | None = None
    isolated: bool = field(default=True, init=False)

    def __post_init__(self) -> None:
        if self.image is not None and not IMAGE_REF.match(self.image):
            raise ValueError(
                "sandbox image must be pinned by digest (name@sha256:... or sha256:...)"
            )

    def image_for(self, task_image: str) -> str:
        image = self.image or task_image
        if not IMAGE_REF.match(image):
            raise SandboxError("image is not pinned by digest")
        return image

    def docker_args(
        self, request: RunRequest, name: str, image_env: dict[str, str] | None = None
    ) -> list[str]:
        environment = {
            "HOME": "/tmp",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTEST_ADDOPTS": "-p no:cacheprovider",
            "CI": "1",
        }
        for key, value in request.env:
            if key in PREPEND_VARS and (image_env or {}).get(key):
                value = f"{value}:{(image_env or {})[key]}"
            environment[key] = value
        args = [
            "docker",
            "run",
            "--rm",
            "--name",
            name,
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=256m",
            "--user",
            "65534:65534",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            str(self.pids_limit),
            "--memory",
            f"{self.memory_mb}m",
            "--memory-swap",
            f"{self.memory_mb}m",
            "--cpus",
            str(self.cpus),
            "--ulimit",
            "fsize=268435456",
            "--init",
            "--log-driver",
            "none",  # the daemon would otherwise keep an unbounded copy of stdout on the host
            "-v",
            f"{request.workspace}:{request.workdir}:rw",
            "-v",
            f"{request.logs_dir}:{LOGS_MOUNT}:rw",
        ]
        for host_dir, container_dir in request.read_only_mounts:
            args += ["-v", f"{host_dir}:{container_dir}:ro"]
        args += ["-w", request.workdir]
        for key, value in environment.items():
            args += ["-e", f"{key}={value}"]
        args += [request.image, "sh", "-c", WRAPPER, "wrapper", request.command]
        return args

    def preflight(self, image: str) -> dict[str, str]:
        """Check that docker has the image; return the environment the image defines."""
        try:
            result = subprocess.run(
                ["docker", "image", "inspect", "--format", "{{json .Config.Env}}", image],
                capture_output=True,
                check=False,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise SandboxError(f"docker is not usable: {exc}") from exc
        if result.returncode != 0:
            tail = result.stderr.decode("utf-8", "replace").strip()[:200]
            raise SandboxError(f"docker cannot find the image: {tail}")
        try:
            entries = json.loads(result.stdout) or []
            pairs = (entry.partition("=") for entry in entries if isinstance(entry, str))
            return {key: value for key, _, value in pairs}
        except ValueError:
            return {}

    def run(self, request: RunRequest) -> RunResult:
        timeout = request.timeout_s
        if self.timeout_cap_s is not None:
            timeout = min(timeout, self.timeout_cap_s)
        image_env = self.preflight(request.image)
        name = f"factory-verify-{uuid.uuid4().hex[:16]}"
        args = self.docker_args(request, name, image_env)
        started = time.monotonic()
        timed_out = False
        collected = _Collected()
        with tempfile.TemporaryFile() as err:
            try:
                process = subprocess.Popen(
                    args, stdout=subprocess.PIPE, stderr=err, stdin=subprocess.DEVNULL
                )
            except OSError as exc:
                raise SandboxError(f"cannot start docker: {exc}") from exc
            assert process.stdout is not None
            reader = threading.Thread(
                target=_drain, args=(process.stdout, collected), daemon=True, name="stdout"
            )
            reader.start()
            try:
                code: int | None = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                self._kill(name)
                process.kill()
                process.wait()
                code = None
            reader.join(timeout=30)
            duration = time.monotonic() - started
            stderr_tail = _tail(err)
        if reader.is_alive():
            # The pipe is still open after the client exited: whatever came is incomplete.
            collected.truncated = True
        stdout = bytes(collected.data)
        if code in DOCKER_FAILURE_CODES:
            raise SandboxError(f"docker failed with exit code {code}: {stderr_tail[-200:]}")
        return RunResult(
            exit_code=code,
            timed_out=timed_out,
            oom_killed=(not timed_out and code == 137),
            duration_s=duration,
            stdout_tail=stdout[-TAIL_BYTES:].decode("utf-8", "replace"),
            stderr_tail=stderr_tail,
            stdout=stdout,
            stdout_truncated=collected.truncated,
        )

    @staticmethod
    def _kill(name: str) -> None:
        for command in (["docker", "kill", name], ["docker", "rm", "-f", name]):
            try:
                subprocess.run(command, capture_output=True, check=False, timeout=60)
            except (OSError, subprocess.SubprocessError):
                continue


def _tail(handle: IO[bytes]) -> str:
    handle.seek(0, 2)
    size = handle.tell()
    handle.seek(max(0, size - TAIL_BYTES))
    return handle.read().decode("utf-8", "replace")


@dataclass
class _Collected:
    data: bytearray = field(default_factory=bytearray)
    truncated: bool = False


def _drain(stream: IO[bytes], collected: _Collected) -> None:
    """Keep the first MAX_STDOUT_BYTES of the stream and discard (but read) the rest."""
    try:
        while chunk := stream.read1(65536):  # type: ignore[attr-defined]
            room = MAX_STDOUT_BYTES - len(collected.data)
            if len(chunk) > room:
                collected.truncated = True
            if room > 0:
                collected.data += chunk[:room]
    except (OSError, ValueError):
        collected.truncated = True
