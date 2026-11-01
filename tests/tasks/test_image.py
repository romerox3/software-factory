"""Extracting the repo from a task image, with Docker replaced by a fake."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from factory.tasks import image as image_module
from factory.tasks.image import ImageError, checkout, extract_repo, read_workdir


class FakeDocker:
    def __init__(self, *, workdir: str = "/testbed", cp_ok: bool = True) -> None:
        self.workdir = workdir
        self.cp_ok = cp_ok
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        self.calls.append(command)
        if command[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(command, 0, f"{self.workdir}\n", "")
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


def test_read_workdir_falls_back_to_the_default_when_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeDocker(workdir="")
    monkeypatch.setattr(image_module.subprocess, "run", fake)

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
