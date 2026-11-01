"""Fixtures for the verifier tests. Docker is required: a missing daemon is a failure."""

from __future__ import annotations

from pathlib import Path

import pytest

from factory.verifier import DockerSandbox

from .support import TASKS, docker, ensure_image, make_mirror


@pytest.fixture(scope="session")
def image() -> str:
    version = docker("version", "--format", "{{.Server.Version}}")
    assert version.returncode == 0, f"docker is required for the verifier tests: {version.stderr}"
    return ensure_image()


@pytest.fixture(scope="session")
def sandbox(image: str) -> DockerSandbox:
    return DockerSandbox(image=image, timeout_cap_s=120)


@pytest.fixture(scope="session")
def py_mirror(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    return make_mirror("py-calc", tmp_path_factory.mktemp("mirror") / "py-calc")


@pytest.fixture(scope="session")
def ts_mirror(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    return make_mirror("ts-calc", tmp_path_factory.mktemp("mirror") / "ts-calc")


@pytest.fixture(scope="session")
def round_store() -> Path:
    return TASKS / "py-calc-round"


@pytest.fixture(scope="session")
def canary_store() -> Path:
    return TASKS / "py-calc-canary"
