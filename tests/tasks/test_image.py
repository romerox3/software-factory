"""Extracting the repo from a task image, with Docker replaced by a fake."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from factory.tasks import image as image_module
from factory.tasks.image import ImageError, checkout, extract_repo, read_workdir


class FakeDocker:
    def __init__(
        self, *, workdir: str = "/testbed", cp_ok: bool = True, testbed_git: bool = True
    ) -> None:
        self.workdir = workdir
        self.cp_ok = cp_ok
        self.testbed_git = testbed_git
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        self.calls.append(command)
        if command[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(command, 0, f"{self.workdir}\n", "")
        if command[1] == "run":
            return subprocess.CompletedProcess(command, 0 if self.testbed_git else 1, "", "")
        if command[1] == "create":
            return subprocess.CompletedProcess(command, 0, "container-id\n", "")
        if command[1] == "cp":
            if not self.cp_ok:
                return subprocess.CompletedProcess(command, 1, "", "no such path")
            Path(command[3], "package.py").write_text("value = 1\n", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 0, "", "")


def test_read_workdir_uses_the_images_working_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeDocker(workdir="/testbed")
    monkeypatch.setattr(image_module.subprocess, "run", fake)

    assert read_workdir("ghcr.io/acme/widgets@sha256:" + "ab" * 32) == "/testbed"


def test_an_empty_workdir_falls_back_to_a_probed_testbed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeDocker(workdir="", testbed_git=True)
    monkeypatch.setattr(image_module.subprocess, "run", fake)

    assert read_workdir("swerebench/sweb.eval@sha256:" + "ab" * 32) == "/testbed"

    probe = next(call for call in fake.calls if call[1] == "run")
    assert probe[:6] == ["docker", "run", "--rm", "--network", "none", "--entrypoint"]
    assert probe[-1] == "test -d /testbed/.git"


def test_dockers_root_workdir_is_treated_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeDocker(workdir="/", testbed_git=True)
    monkeypatch.setattr(image_module.subprocess, "run", fake)

    assert read_workdir("swerebench/sweb.eval@sha256:" + "ab" * 32) == "/testbed"


def test_an_empty_workdir_without_a_checkout_keeps_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeDocker(workdir="", testbed_git=False)
    monkeypatch.setattr(image_module.subprocess, "run", fake)

    assert read_workdir("python:3.12-slim") == "/workspace"


def test_a_failing_probe_falls_back_to_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_docker(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[1] == "run":
            raise OSError("docker: not found")
        return subprocess.CompletedProcess(command, 0, "\n", "")

    monkeypatch.setattr(image_module.subprocess, "run", failing_docker)

    assert read_workdir("python:3.12-slim") == "/workspace"


def test_extract_repo_copies_the_working_directory_and_removes_the_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeDocker(workdir="/testbed")
    monkeypatch.setattr(image_module.subprocess, "run", fake)
    dest = tmp_path / "repo"

    workdir = extract_repo("ghcr.io/acme/widgets@sha256:" + "ab" * 32, dest)

    assert workdir == "/testbed"
    assert (dest / "package.py").is_file()
    assert ["docker", "cp", "container-id:/testbed/.", str(dest)] in fake.calls
    assert ["docker", "rm", "--force", "container-id"] in fake.calls


def test_a_failed_copy_still_removes_the_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeDocker(cp_ok=False)
    monkeypatch.setattr(image_module.subprocess, "run", fake)

    with pytest.raises(ImageError, match="cannot extract"):
        extract_repo("ghcr.io/acme/widgets@sha256:" + "ab" * 32, tmp_path / "repo")

    assert ["docker", "rm", "--force", "container-id"] in fake.calls


def test_extract_repo_refuses_an_existing_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    monkeypatch.setattr(image_module.subprocess, "run", FakeDocker())

    with pytest.raises(ImageError, match="already exists"):
        extract_repo("ghcr.io/acme/widgets@sha256:" + "ab" * 32, target)


def test_checkout_reports_git_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_git(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, "", "unknown revision")

    monkeypatch.setattr(image_module.subprocess, "run", failing_git)

    with pytest.raises(ImageError, match="unknown revision"):
        checkout(tmp_path, "0" * 40)
