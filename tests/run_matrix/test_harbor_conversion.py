"""Converting a task to Harbor: stale output is replaced, not reused blindly."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from factory.run_matrix import Deps, _convert_tasks
from factory.tasks.to_harbor import tree_digest

from .support import TASK_ID, write_store

EXECUTOR = "claude-code"
WALL_S = 1800
KEY = (EXECUTOR, WALL_S, TASK_ID)


class WritingToHarbor:
    """Writes a minimal task tree, like ``to_harbor`` but without validation."""

    def __init__(self, script: str = "#!/bin/sh\necho old\n") -> None:
        self.script = script
        self.fail = False
        self.calls = 0

    def __call__(self, visible_task_dir: Path, out_dir: Path, **_kwargs: object) -> Path:
        self.calls += 1
        if self.fail:
            raise RuntimeError("converter exploded")
        target = Path(out_dir) / Path(visible_task_dir).name
        (target / "tests").mkdir(parents=True)
        script = target / "tests" / "test.sh"
        script.write_text(self.script, encoding="utf-8")
        script.chmod(0o755)
        return target


def _args(store: Path, work: Path) -> argparse.Namespace:
    return argparse.Namespace(store=store, work=work, gateway_host="gateway.example")


def _target(work: Path) -> Path:
    return work / "harbor" / f"{EXECUTOR}-t{WALL_S}" / TASK_ID


def _staging_dirs(work: Path) -> list[Path]:
    parent = _target(work).parent
    return [path for path in parent.iterdir() if path.name.startswith(f".{TASK_ID}.")]


def test_identical_output_keeps_the_existing_task_dir(tmp_path: Path) -> None:
    store = write_store(tmp_path)
    work = tmp_path / "work"
    args = _args(store, work)
    converter = WritingToHarbor()
    deps = Deps(to_harbor=converter)

    first, first_errors = _convert_tasks([TASK_ID], [(EXECUTOR, WALL_S)], args, deps)
    target = _target(work)
    inode = target.stat().st_ino

    second, second_errors = _convert_tasks([TASK_ID], [(EXECUTOR, WALL_S)], args, deps)

    assert first_errors == second_errors == {}
    assert first == second == {KEY: target}
    assert target.stat().st_ino == inode
    assert (target / "tests" / "test.sh").read_text(encoding="utf-8") == converter.script
    assert _staging_dirs(work) == []


def test_changed_output_replaces_the_stale_task_dir(tmp_path: Path) -> None:
    store = write_store(tmp_path)
    work = tmp_path / "work"
    args = _args(store, work)
    converter = WritingToHarbor()
    deps = Deps(to_harbor=converter)

    _convert_tasks([TASK_ID], [(EXECUTOR, WALL_S)], args, deps)
    target = _target(work)
    (target / "stale.txt").write_text("gone\n", encoding="utf-8")

    converter.script = "#!/bin/sh\necho new\n"
    converted, errors = _convert_tasks([TASK_ID], [(EXECUTOR, WALL_S)], args, deps)

    assert errors == {}
    assert converted == {KEY: target}
    assert (target / "tests" / "test.sh").read_text(encoding="utf-8") == converter.script
    assert not (target / "stale.txt").exists()
    assert _staging_dirs(work) == []


def test_conversion_error_leaves_the_existing_task_dir_alone(tmp_path: Path) -> None:
    store = write_store(tmp_path)
    work = tmp_path / "work"
    args = _args(store, work)
    converter = WritingToHarbor()
    deps = Deps(to_harbor=converter)

    _convert_tasks([TASK_ID], [(EXECUTOR, WALL_S)], args, deps)
    target = _target(work)
    before = (target / "tests" / "test.sh").read_text(encoding="utf-8")

    converter.fail = True
    converted, errors = _convert_tasks([TASK_ID], [(EXECUTOR, WALL_S)], args, deps)

    assert converted == {}
    assert "converter exploded" in errors[KEY]
    assert (target / "tests" / "test.sh").read_text(encoding="utf-8") == before
    assert _staging_dirs(work) == []


def test_tree_digest_ignores_mtime(tmp_path: Path) -> None:
    root = tmp_path / "task"
    (root / "tests").mkdir(parents=True)
    script = root / "tests" / "test.sh"
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    script.chmod(0o755)

    digest = tree_digest(root)
    os.utime(script, (1_000_000, 1_000_000))

    assert tree_digest(root) == digest


def test_tree_digest_changes_with_content(tmp_path: Path) -> None:
    root = tmp_path / "task"
    root.mkdir()
    script = root / "test.sh"
    script.write_text("old\n", encoding="utf-8")
    digest = tree_digest(root)

    script.write_text("new\n", encoding="utf-8")

    assert tree_digest(root) != digest


def test_tree_digest_changes_with_a_renamed_file(tmp_path: Path) -> None:
    root = tmp_path / "task"
    root.mkdir()
    original = root / "old.sh"
    original.write_text("same\n", encoding="utf-8")
    digest = tree_digest(root)

    original.rename(root / "new.sh")

    assert tree_digest(root) != digest


def test_tree_digest_changes_with_the_executable_bit(tmp_path: Path) -> None:
    root = tmp_path / "task"
    root.mkdir()
    script = root / "test.sh"
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    script.chmod(0o644)
    digest = tree_digest(root)

    script.chmod(0o755)

    assert tree_digest(root) != digest


def test_tree_digest_follows_a_symlink_target(tmp_path: Path) -> None:
    root = tmp_path / "task"
    root.mkdir()
    (root / "old.sh").write_text("same\n", encoding="utf-8")
    (root / "new.sh").write_text("same\n", encoding="utf-8")
    (root / "link.sh").symlink_to("old.sh")
    digest = tree_digest(root)

    (root / "link.sh").unlink()
    (root / "link.sh").symlink_to("new.sh")

    assert tree_digest(root) != digest
