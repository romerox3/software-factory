"""Tests for the fresh-init snapshot builder (threat T15)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from factory.snapshot.fresh_init import build_snapshot

# Keep the fixtures independent from the developer's global/system git config.
GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}
SECRET = "FUTURE-SECRET-123"


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=GIT_ENV,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def git_bytes(repo: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=GIT_ENV,
        check=True,
        capture_output=True,
    )
    return result.stdout


def new_repo(path: Path) -> Path:
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    return path


def commit_all(repo: Path, message: str = "commit") -> str:
    git(repo, "add", "-A")
    git(
        repo,
        "-c",
        "user.name=test",
        "-c",
        "user.email=test@invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-q",
        "-m",
        message,
    )
    return git(repo, "rev-parse", "HEAD")


def all_objects(repo: Path) -> list[tuple[str, str]]:
    listing = git(repo, "cat-file", "--batch-all-objects", "--batch-check")
    return [tuple(line.split()[:2]) for line in listing.splitlines() if line]


def make_source_with_secret(tmp_path: Path) -> tuple[Path, str, str, str]:
    source = new_repo(tmp_path / "source")
    (source / "app.txt").write_text("base\n", encoding="utf-8")
    base = commit_all(source, "A")
    (source / "secret.txt").write_text(f"{SECRET}\n", encoding="utf-8")
    future = commit_all(source, "B")
    secret_blob = git(source, "rev-parse", f"{future}:secret.txt")
    return source, base, future, secret_blob


def test_snapshot_has_no_trace_of_later_commits(tmp_path: Path) -> None:
    source, base, future, secret_blob = make_source_with_secret(tmp_path)
    dest = tmp_path / "snapshot"

    sha = build_snapshot(source, base, dest)

    # Exactly one commit and exactly the base tree.
    assert git(dest, "log", "--all", "--format=%H").splitlines() == [sha]
    assert git(dest, "rev-parse", f"{sha}^{{tree}}") == git(source, "rev-parse", f"{base}^{{tree}}")

    # The future commit and its blob are absent from every object.
    objects = all_objects(dest)
    object_ids = {object_id for object_id, _ in objects}
    assert future not in object_ids
    assert secret_blob not in object_ids

    # No object (tree names included) mentions the secret or its blob id.
    for object_id, _ in objects:
        content = git_bytes(dest, "cat-file", "-p", object_id)
        assert SECRET.encode() not in content
        assert secret_blob.encode() not in content

    # No working-tree file leaked it either.
    for path in dest.rglob("*"):
        if path.is_file() and not path.is_relative_to(dest / ".git"):
            assert SECRET.encode() not in path.read_bytes()

    # fsck does not find the secret as a dangling/lost object.
    fsck = subprocess.run(
        ["git", "fsck", "--lost-found", "--no-progress"],
        cwd=dest,
        env=GIT_ENV,
        check=True,
        capture_output=True,
        text=True,
    )
    assert SECRET not in fsck.stdout + fsck.stderr
    assert secret_blob not in fsck.stdout + fsck.stderr
    lost_found = dest / ".git" / "lost-found"
    lost_files = [p for p in lost_found.rglob("*") if p.is_file()] if lost_found.exists() else []
    assert lost_files == []


def test_export_ignore_file_is_kept(tmp_path: Path) -> None:
    source = new_repo(tmp_path / "source")
    (source / ".gitattributes").write_text("kept.txt export-ignore\n", encoding="utf-8")
    (source / "kept.txt").write_text("keep me\n", encoding="utf-8")
    (source / "normal.txt").write_text("normal\n", encoding="utf-8")
    base = commit_all(source)
    dest = tmp_path / "snapshot"

    build_snapshot(source, base, dest)

    assert (dest / "kept.txt").read_text(encoding="utf-8") == "keep me\n"
    assert (dest / "normal.txt").read_text(encoding="utf-8") == "normal\n"
    tracked = git(dest, "ls-files").splitlines()
    assert sorted(tracked) == [".gitattributes", "kept.txt", "normal.txt"]


def test_snapshot_has_no_remotes_tags_or_extra_branches(tmp_path: Path) -> None:
    source, base, _, _ = make_source_with_secret(tmp_path)
    git(source, "remote", "add", "origin", "https://example.invalid/repo.git")
    git(source, "tag", "v1")
    dest = tmp_path / "snapshot"

    build_snapshot(source, base, dest)

    assert git(dest, "remote") == ""
    assert git(dest, "tag") == ""
    refs = git(dest, "for-each-ref", "--format=%(refname)").splitlines()
    assert len([ref for ref in refs if ref.startswith("refs/heads/")]) == 1
    assert [ref for ref in refs if ref.startswith(("refs/remotes/", "refs/tags/"))] == []


def test_same_base_gives_same_sha(tmp_path: Path) -> None:
    source = new_repo(tmp_path / "source")
    (source / "app.txt").write_text("base\n", encoding="utf-8")
    base = commit_all(source, "A")

    first = build_snapshot(source, base, tmp_path / "first")

    # A later commit in the source must not influence the snapshot of the base.
    (source / "later.txt").write_text("later\n", encoding="utf-8")
    commit_all(source, "B")

    second = build_snapshot(source, base, tmp_path / "second")
    assert first == second


def test_non_empty_dest_raises_value_error(tmp_path: Path) -> None:
    source, base, _, _ = make_source_with_secret(tmp_path)
    dest = tmp_path / "snapshot"
    dest.mkdir()
    (dest / "already-here.txt").write_text("", encoding="utf-8")

    with pytest.raises(ValueError):
        build_snapshot(source, base, dest)


def test_missing_base_raises_with_git_stderr(tmp_path: Path) -> None:
    source, _, _, _ = make_source_with_secret(tmp_path)

    with pytest.raises(RuntimeError, match="read-tree"):
        build_snapshot(source, "does-not-exist", tmp_path / "snapshot")


def test_source_repo_keeps_head_index_and_status(tmp_path: Path) -> None:
    source, base, _, _ = make_source_with_secret(tmp_path)
    head_before = git(source, "rev-parse", "HEAD")
    status_before = git(source, "status", "--porcelain")
    index_before = (source / ".git" / "index").read_bytes()

    build_snapshot(source, base, tmp_path / "snapshot")

    assert git(source, "rev-parse", "HEAD") == head_before
    assert (source / ".git" / "index").read_bytes() == index_before
    assert git(source, "status", "--porcelain") == status_before


def install_failing_pre_commit(hooks: Path, witness: Path) -> Path:
    """Return a git config path whose global ``core.hooksPath`` is ``hooks``."""
    hooks.mkdir()
    hook = hooks / "pre-commit"
    hook.write_text(f"#!/bin/sh\necho ran > '{witness}'\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    config = hooks.parent / "gitconfig"
    config.write_text(f"[core]\n\thooksPath = {hooks}\n", encoding="utf-8")
    return config


def test_snapshot_ignores_user_hooks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source, base, _, _ = make_source_with_secret(tmp_path)
    witness = tmp_path / "witness"
    config = install_failing_pre_commit(tmp_path / "hooks", witness)
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": str(config)}
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))

    # Control: the very same global config does reach a plain repository, so a
    # commit without isolation runs the hook and fails.
    control = tmp_path / "control"
    control.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=control, env=env, check=True)
    (control / "file.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=control, env=env, check=True)
    control_commit = subprocess.run(
        [
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@invalid",
            "commit",
            "-q",
            "-m",
            "control",
        ],
        cwd=control,
        env=env,
        capture_output=True,
        check=False,
    )
    assert control_commit.returncode != 0
    assert witness.exists()
    witness.unlink()

    build_snapshot(source, base, tmp_path / "snapshot")

    assert not witness.exists()


def test_snapshot_has_no_hooks(tmp_path: Path) -> None:
    source, base, _, _ = make_source_with_secret(tmp_path)
    dest = tmp_path / "snapshot"

    build_snapshot(source, base, dest)

    hooks = dest / ".git" / "hooks"
    assert not hooks.exists() or list(hooks.iterdir()) == []


def test_snapshot_branch_is_main(tmp_path: Path) -> None:
    source, base, _, _ = make_source_with_secret(tmp_path)
    dest = tmp_path / "snapshot"

    build_snapshot(source, base, dest)

    assert git(dest, "symbolic-ref", "--short", "HEAD") == "main"
    assert git(dest, "branch", "--format=%(refname:short)").splitlines() == ["main"]
