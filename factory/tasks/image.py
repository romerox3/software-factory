"""Pull a pinned image, read its working directory and extract the repository.

The task image already holds the repository the task was built from, at its
``base_commit``, with its full history and the editable install that makes the
tests import that copy. Revalidation therefore starts from this checkout instead
of cloning from the network. ``docker cp`` is used through a stopped container so
nothing of the image has to run.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from factory.tasks.workdir import DEFAULT_WORKDIR


class ImageError(RuntimeError):
    """Docker could not pull, inspect, extract or remove the image."""


def pull_image(image: str) -> None:
    """Pull ``image`` (``name@sha256:...``) so later steps cannot drift."""
    _docker(["pull", image], f"cannot pull {image}")


def remove_image(image: str) -> None:
    """Remove ``image`` to keep the tower's disk under control."""
    _docker(["image", "rm", "--force", image], f"cannot remove {image}", check=False)


def read_workdir(image: str) -> str:
    """Return the image's ``WorkingDir``; empty means Docker's root, ``/testbed`` in real tasks."""
    result = _docker(
        ["image", "inspect", "--format", "{{.Config.WorkingDir}}", image],
        f"cannot inspect {image}",
    )
    return result.stdout.strip() or DEFAULT_WORKDIR


def extract_repo(image: str, dest: Path) -> str:
    """Copy the image's working directory to ``dest`` and return that directory."""
    dest = Path(dest)
    if dest.exists():
        raise ImageError(f"extraction target already exists: {dest}")
    workdir = read_workdir(image)
    container = _docker(["create", image], f"cannot create a container from {image}").stdout.strip()
    if not container:
        raise ImageError(f"docker create returned no container for {image}")
    try:
        dest.mkdir(parents=True)
        source = f"{container}:{workdir.rstrip('/')}/."
        _docker(
            ["cp", source, str(dest)],
            f"cannot extract {workdir} from {image}",
        )
    finally:
        _docker(["rm", "--force", container], "cannot remove the extraction container", check=False)
    return workdir


def checkout(repo: Path, commit: str) -> None:
    """Move the extracted checkout to ``commit`` without keeping local modifications."""
    result = subprocess.run(
        ["git", "-C", str(repo), "checkout", "-qf", commit],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = (result.stderr or "").strip() or "git wrote nothing to stderr"
        raise ImageError(f"cannot check out {commit}: {stderr}")


def _docker(args: list[str], error: str, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            ["docker", *args], check=False, capture_output=True, text=True, timeout=1800
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ImageError(f"{error}: {exc}") from exc
    if check and result.returncode != 0:
        stderr = (result.stderr or "").strip()[:300] or "docker wrote nothing to stderr"
        raise ImageError(f"{error}: {stderr}")
    return result
