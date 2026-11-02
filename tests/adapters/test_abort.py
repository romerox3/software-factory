"""The agent's abort channel, read from the exported workspace."""

from __future__ import annotations

from pathlib import Path

import pytest

from factory.adapters import InvalidAbort, read_abort

from .support import set_file


def _abort_path(workspace: Path) -> Path:
    return workspace / ".factory" / "abort.json"


def test_missing_abort_is_none(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    assert read_abort(workspace) is None


def test_valid_abort_is_returned_and_normalized(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    set_file(
        workspace,
        ".factory/abort.json",
        '{"reason": "spec and tests disagree", "spec_refs": ["specs/a.md"], "test_refs": []}',
    )
    assert read_abort(workspace) == {
        "reason": "spec and tests disagree",
        "spec_refs": ["specs/a.md"],
        "test_refs": [],
    }


def test_custom_workdir_reads_the_abort_document_from_that_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    set_file(workspace, ".factory/abort.json", '{"reason": "spec conflict"}')

    assert read_abort(workspace, workdir="/testbed") == {"reason": "spec conflict"}


def test_reason_is_required(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    set_file(workspace, ".factory/abort.json", '{"spec_refs": []}')
    with pytest.raises(InvalidAbort, match="reason"):
        read_abort(workspace)


def test_empty_reason_is_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    set_file(workspace, ".factory/abort.json", '{"reason": "  "}')
    with pytest.raises(InvalidAbort, match="reason"):
        read_abort(workspace)


def test_unknown_keys_are_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    set_file(workspace, ".factory/abort.json", '{"reason": "x", "raw": "y"}')
    with pytest.raises(InvalidAbort, match="unknown keys"):
        read_abort(workspace)


def test_refs_must_be_strings(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    set_file(workspace, ".factory/abort.json", '{"reason": "x", "spec_refs": [1]}')
    with pytest.raises(InvalidAbort, match="spec_refs"):
        read_abort(workspace)


def test_null_refs_are_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    set_file(workspace, ".factory/abort.json", '{"reason": "x", "test_refs": null}')
    with pytest.raises(InvalidAbort, match="test_refs"):
        read_abort(workspace)


def test_invalid_json_is_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    set_file(workspace, ".factory/abort.json", "{not json")
    with pytest.raises(InvalidAbort, match="not valid JSON"):
        read_abort(workspace)


def test_path_outside_the_workspace_is_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(InvalidAbort, match="outside|escapes"):
        read_abort(workspace, "/etc/abort.json")


def test_symlinked_abort_is_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside.json"
    outside.write_text('{"reason": "x"}', encoding="utf-8")
    target = _abort_path(workspace)
    target.parent.mkdir(parents=True)
    target.symlink_to(outside)
    with pytest.raises(InvalidAbort, match="regular file|escapes"):
        read_abort(workspace)
