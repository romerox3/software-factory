"""The host diff: snapshot's git, neutral attributes and the T30 trap fixture."""

from __future__ import annotations

from pathlib import Path

import pytest

from factory.adapters import compute_diff, empty_diff, split_factory_files

from .support import append_file, export_workspace, make_snapshot, set_file

TRAP_ATTRIBUTES = "tests/** -diff -text\n*.py filter=cleanpy diff=pycalc\n"

CODE_PATCH = (
    b"diff --git a/src/calc.py b/src/calc.py\n"
    b"index 1111111..2222222 100644\n"
    b"--- a/src/calc.py\n"
    b"+++ b/src/calc.py\n"
    b"@@ -1,2 +1,2 @@\n"
    b"-old\n"
    b"+new\n"
    b" keep\n"
)

ABORT_PATCH = (
    b"diff --git a/.factory/abort.json b/.factory/abort.json\n"
    b"new file mode 100644\n"
    b"index 0000000..1111111\n"
    b"--- /dev/null\n"
    b"+++ b/.factory/abort.json\n"
    b"@@ -0,0 +1 @@\n"
    b'+{"reason": "spec and tests disagree"}\n'
)

BINARY_PATCH = (
    b"diff --git a/asset.bin b/asset.bin\n"
    b"new file mode 100644\n"
    b"index 0000000..2222222\n"
    b"GIT binary patch\n"
    b"literal 3\n"
    b"KcmZ?0N?A=0\n"
    b"\n"
    b"literal 0\n"
    b"HcmV?d00001\n"
    b"\n"
)


def _change(workspace: Path) -> None:
    append_file(workspace, "src/calc/__init__.py", "\ndef twice(value):\n    return value * 2\n")
    append_file(workspace, "tests/test_calc.py", "\n# visible test touched by the agent\n")


def _tamper_agent_git(workspace: Path) -> None:
    with (workspace / ".git" / "config").open("a", encoding="utf-8") as handle:
        handle.write(
            "[diff]\n\texternal = /bin/false\n"
            '[filter "cleanpy"]\n\tclean = /bin/false\n'
            '[diff "pycalc"]\n\ttextconv = /bin/false\n'
        )
    set_file(workspace, ".git/info/attributes", TRAP_ATTRIBUTES)


def test_diff_survives_the_tamper_gitattributes_trap(tmp_path: Path) -> None:
    clean_snapshot, clean_base = make_snapshot(tmp_path / "clean")
    trap_snapshot, trap_base = make_snapshot(tmp_path / "trap", trap=True)
    clean_workspace = export_workspace(clean_snapshot, tmp_path / "clean")
    trap_workspace = export_workspace(trap_snapshot, tmp_path / "trap")
    _change(clean_workspace)
    _change(trap_workspace)
    _tamper_agent_git(trap_workspace)

    clean = compute_diff(clean_workspace, clean_snapshot / ".git", clean_base)
    trapped = compute_diff(trap_workspace, trap_snapshot / ".git", trap_base)

    assert trapped.patch == clean.patch
    assert b"tests/test_calc.py" in trapped.patch
    assert b"src/calc/__init__.py" in trapped.patch
    assert trapped.files_changed == 2
    assert trapped.lines_added == 5
    assert trapped.lines_removed == 0


def test_agent_dot_git_is_replaced_by_the_snapshot(tmp_path: Path) -> None:
    snapshot, base = make_snapshot(tmp_path / "clean")
    workspace = export_workspace(snapshot, tmp_path / "clean")
    append_file(workspace, "src/calc/__init__.py", "\n# changed\n")
    _tamper_agent_git(workspace)

    result = compute_diff(workspace, snapshot / ".git", base)

    assert b"# changed" in result.patch
    assert result.files_changed == 1


def test_unchanged_workspace_has_an_empty_diff(tmp_path: Path) -> None:
    snapshot, base = make_snapshot(tmp_path / "clean")
    workspace = export_workspace(snapshot, tmp_path / "clean")

    result = compute_diff(workspace, snapshot / ".git", base)

    assert result.patch == b""
    assert result == empty_diff()


def test_binary_changes_are_included(tmp_path: Path) -> None:
    snapshot, base = make_snapshot(tmp_path / "clean")
    workspace = export_workspace(snapshot, tmp_path / "clean")
    (workspace / "asset.bin").write_bytes(b"\x00\x01\x02")
    set_file(workspace, ".gitattributes", "asset.bin -diff\n")

    result = compute_diff(workspace, snapshot / ".git", base)

    assert b"GIT binary patch" in result.patch
    assert b"asset.bin" in result.patch
    assert result.files_changed == 2


def test_bad_inputs_are_rejected(tmp_path: Path) -> None:
    snapshot, base = make_snapshot(tmp_path / "clean")
    workspace = export_workspace(snapshot, tmp_path / "clean")

    with pytest.raises(ValueError, match="workspace"):
        compute_diff(tmp_path / "missing", snapshot / ".git", base)
    with pytest.raises(ValueError, match=r"\.git"):
        compute_diff(workspace, tmp_path / "missing", base)
    with pytest.raises(ValueError, match="40-character"):
        compute_diff(workspace, snapshot / ".git", "abc")


def test_split_factory_files_keeps_a_patch_without_factory_files() -> None:
    kept, files = split_factory_files(CODE_PATCH)

    assert kept == CODE_PATCH
    assert files == {}


def test_split_factory_files_removes_the_only_factory_file() -> None:
    kept, files = split_factory_files(ABORT_PATCH)

    assert kept == b""
    assert files == {".factory/abort.json": b'{"reason": "spec and tests disagree"}\n'}


def test_split_factory_files_keeps_code_byte_for_byte() -> None:
    kept, files = split_factory_files(ABORT_PATCH + CODE_PATCH)

    assert kept == CODE_PATCH
    assert files == {".factory/abort.json": b'{"reason": "spec and tests disagree"}\n'}


def test_split_factory_files_does_not_touch_binary_sections() -> None:
    kept, files = split_factory_files(ABORT_PATCH + BINARY_PATCH)

    assert kept == BINARY_PATCH
    assert files == {".factory/abort.json": b'{"reason": "spec and tests disagree"}\n'}
