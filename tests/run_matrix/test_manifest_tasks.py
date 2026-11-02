"""The run draws its tasks from the public manifest."""

from __future__ import annotations

from pathlib import Path

import pytest

from factory.run_matrix import Deps, main, manifest_task_ids, select_task_ids

from .support import (
    FakeHarbor,
    FakeKeys,
    FakeVerifier,
    arm,
    write_arms,
    write_manifest,
    write_store,
)


def test_manifest_task_ids_are_read_in_order(tmp_path: Path) -> None:
    path = write_manifest(tmp_path / "manifest.json", ["t2", "t1", "t2"])

    assert manifest_task_ids(path) == ["t2", "t1"]


def test_manifest_selects_exactly_its_tasks(tmp_path: Path) -> None:
    store = write_store(tmp_path, ["t1", "t2"])

    assert select_task_ids(store, write_manifest(tmp_path / "m.json", ["t2"]), []) == ["t2"]


def test_task_filter_applies_within_the_manifest(tmp_path: Path) -> None:
    store = write_store(tmp_path, ["t1", "t2"])
    manifest = write_manifest(tmp_path / "m.json", ["t2"])

    with pytest.raises(ValueError, match="unknown task"):
        select_task_ids(store, manifest, ["t1"])


def test_a_manifest_task_missing_from_the_store_fails(tmp_path: Path) -> None:
    store = write_store(tmp_path, ["t1"])
    manifest = write_manifest(tmp_path / "m.json", ["t1", "gone"])

    with pytest.raises(ValueError, match="not valid in the store: gone"):
        select_task_ids(store, manifest, [])


def test_manifest_needs_task_ids(tmp_path: Path) -> None:
    path = tmp_path / "m.json"
    path.write_text('{"tasks": [{"dataset": "x"}]}', encoding="utf-8")

    with pytest.raises(ValueError, match="task_id"):
        manifest_task_ids(path)


def test_run_only_plans_the_manifest_tasks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = write_store(tmp_path, ["t1", "t2"])
    arms = write_arms(tmp_path / "arms.json", [arm("A1", k=1)])
    manifest = write_manifest(tmp_path / "m.json", ["t2"])
    args = [
        "run",
        "--store",
        str(store),
        "--arms",
        str(arms),
        "--manifest",
        str(manifest),
        "--out",
        str(tmp_path / "out"),
        "--work",
        str(tmp_path / "work"),
        "--gateway-url",
        "http://gateway:4000/v1",
        "--dry-run",
    ]

    code = main(
        args,
        deps=Deps(
            key_client=FakeKeys(),
            harbor=FakeHarbor(),
            verifier=FakeVerifier(),
            to_harbor=lambda *_a, **_k: tmp_path,
        ),
    )

    assert code == 0
    assert capsys.readouterr().out.splitlines()[0] == "a1-t2-r1-a1"
