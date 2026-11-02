"""Importing public HF rows must keep the hidden part out of the visible tree."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from factory.tasks.import_hf import (
    REBENCH_ENV_PREFIX,
    download_split,
    load_rows,
    load_split,
    select,
    update_manifest,
    write_task,
)
from factory.tasks.to_harbor import to_harbor

FIXTURES = Path(__file__).parents[2] / "fixtures" / "hf"
REBENCH = FIXTURES / "rebench-sample.jsonl"
MULTILANG = FIXTURES / "multilang-ts-sample.jsonl"
CUTOFF = datetime(2026, 1, 1, tzinfo=UTC)
REVISION = "f" * 40
EXCLUDED_PATH_REGEXES = [r"(^|/)auth/"]
BUDGET = {"usd": 1.0, "max_turns": 24, "timeout_sec": 600}
NO_DIGEST_INSTANCE = "acme__widgets-1004"
REBENCH_DATASET = "nebius/SWE-rebench-leaderboard"


def digest_for(image: str) -> str:
    return f"sha256:{sha256(image.encode()).hexdigest()}"


def digests_for(rows: list[dict]) -> dict[str, str]:
    return {
        row["docker_image"]: digest_for(row["docker_image"])
        for row in rows
        if row["instance_id"] != NO_DIGEST_INSTANCE
    }


def select_all(rows: list[dict], source: str = "rebench", seed: int = 0):
    return select(
        rows,
        source=source,
        cutoff=CUTOFF,
        digests=digests_for(rows),
        excluded_path_regexes=EXCLUDED_PATH_REGEXES,
        seed=seed,
        limit=100,
    )


def test_sample_rows_yield_the_expected_tasks_and_rejections() -> None:
    rows = load_rows(REBENCH)

    selected, rejections = select_all(rows)

    assert [(candidate.instance_id, candidate.task_class) for candidate in selected] == [
        ("acme__widgets-1001", "C1"),
        ("acme__widgets-1002", "C2"),
        ("acme__widgets-1008", "C1"),
        ("acme__widgets-1009", "C1"),
        ("acme__widgets-1010", "C1"),
    ]
    assert {rejection.instance_id: rejection.reason for rejection in rejections} == {
        "acme__widgets-1003": "before_cutoff",
        "acme__widgets-1004": "no_digest",
        "acme__widgets-1005": "excluded_path",
        "acme__widgets-1006": "too_large",
        "acme__widgets-1007": "no_f2p",
    }


def test_multilang_framework_comes_from_the_test_command_and_jest_is_rejected() -> None:
    rows = load_rows(MULTILANG)

    selected, rejections = select_all(rows, source="multilang")

    assert [(candidate.instance_id, candidate.framework) for candidate in selected] == [
        ("acme__webui-2001", "vitest")
    ]
    assert {rejection.instance_id: rejection.reason for rejection in rejections} == {
        "acme__webui-2002": "unsupported_test_command",
        "acme__webui-2003": "unsupported_test_command",
    }
    candidate = selected[0]
    assert candidate.visible_command == "npx vitest run"
    assert candidate.verifier_command == (
        "npm ci && npx vitest run --reporter=junit --outputFile=/logs/verifier/junit.xml"
    )
    assert not candidate.visible_command.startswith("export PATH")
    assert not candidate.verifier_command.startswith("export PATH")


def test_multilang_vitest_command_replaces_other_reporters() -> None:
    row = dict(load_rows(MULTILANG)[0])
    row["test_cmds"] = ["npx vitest run --reporter=default --outputFile=report.json"]

    selected, rejections = select(
        [row],
        source="multilang",
        cutoff=CUTOFF,
        digests=digests_for([row]),
        excluded_path_regexes=EXCLUDED_PATH_REGEXES,
        seed=0,
        limit=1,
    )

    assert rejections == []
    assert selected[0].verifier_command == (
        "npm ci && npx vitest run --reporter=junit --outputFile=/logs/verifier/junit.xml"
    )


def test_rebench_uses_the_rows_own_test_command() -> None:
    row = dict(load_rows(REBENCH)[0])
    row["install_config"] = {"test_cmd": "pytest -q tests/test_widgets.py"}

    selected, _ = select(
        [row],
        source="rebench",
        cutoff=CUTOFF,
        digests=digests_for([row]),
        excluded_path_regexes=EXCLUDED_PATH_REGEXES,
        seed=0,
        limit=1,
    )

    assert selected[0].verifier_command == (
        f"{REBENCH_ENV_PREFIX}pytest -q tests/test_widgets.py --junitxml=/logs/verifier/junit.xml"
    )
    assert selected[0].visible_command == f"{REBENCH_ENV_PREFIX}pytest -q tests/test_widgets.py"


def test_rebench_uses_the_conda_env_when_the_row_allows_it() -> None:
    row = dict(load_rows(REBENCH)[0])
    row["install_config"] = {
        "test_cmd": "pytest -q tests/test_widgets.py",
        "no_use_env": False,
    }

    selected, _ = select(
        [row],
        source="rebench",
        cutoff=CUTOFF,
        digests=digests_for([row]),
        excluded_path_regexes=EXCLUDED_PATH_REGEXES,
        seed=0,
        limit=1,
    )

    candidate = selected[0]
    assert candidate.visible_command == f"{REBENCH_ENV_PREFIX}pytest -q tests/test_widgets.py"
    assert candidate.verifier_command == (
        f"{REBENCH_ENV_PREFIX}pytest -q tests/test_widgets.py --junitxml=/logs/verifier/junit.xml"
    )


def test_rebench_skips_the_conda_env_when_the_row_opts_out() -> None:
    row = dict(load_rows(REBENCH)[0])
    row["install_config"] = {
        "test_cmd": "pytest -q tests/test_widgets.py",
        "no_use_env": True,
    }

    selected, _ = select(
        [row],
        source="rebench",
        cutoff=CUTOFF,
        digests=digests_for([row]),
        excluded_path_regexes=EXCLUDED_PATH_REGEXES,
        seed=0,
        limit=1,
    )

    candidate = selected[0]
    assert candidate.visible_command == "pytest -q tests/test_widgets.py"
    assert candidate.verifier_command == (
        "pytest -q tests/test_widgets.py --junitxml=/logs/verifier/junit.xml"
    )


def test_sampling_is_stable_for_one_seed_and_can_change_with_another() -> None:
    rows = load_rows(REBENCH)
    options = {
        "source": "rebench",
        "cutoff": CUTOFF,
        "digests": digests_for(rows),
        "excluded_path_regexes": EXCLUDED_PATH_REGEXES,
        "limit": 2,
    }

    first, _ = select(rows, seed=0, **options)
    repeated, _ = select(rows, seed=0, **options)
    different, _ = select(rows, seed=1, **options)

    eligible, _ = select(rows, seed=0, **{**options, "limit": 100})
    assert len(eligible) >= 5
    assert [candidate.instance_id for candidate in first] == [
        candidate.instance_id for candidate in repeated
    ]
    assert [candidate.instance_id for candidate in different] != [
        candidate.instance_id for candidate in first
    ]


def added_lines(*patches: str) -> set[str]:
    lines = set()
    for patch in patches:
        for line in patch.splitlines():
            if line.startswith("+++"):
                continue
            if line.startswith("+"):
                content = line[1:].strip()
                if content:
                    lines.add(content)
    return lines


def test_write_task_keeps_the_hidden_material_out_of_the_visible_tree(
    tmp_path: Path,
) -> None:
    rows = load_rows(REBENCH)
    selected, _ = select_all(rows)
    candidate = next(item for item in selected if item.instance_id == "acme__widgets-1001")

    store = tmp_path / "store"
    task_id = write_task(
        candidate, store, dataset=REBENCH_DATASET, revision=REVISION, budget=BUDGET
    )

    assert task_id == "acme__widgets-1001"
    visible = store / "visible" / task_id
    hidden = store / "hidden" / task_id
    assert sorted(path.name for path in hidden.iterdir()) == [
        "f2p.json",
        "gold.patch",
        "p2p.json",
        "test.patch",
        "verifier.json",
    ]

    task = json.loads((visible / "factory.task.json").read_text(encoding="utf-8"))
    assert task["class"] == "C1"
    assert task["image"] == f"ghcr.io/acme/widgets-1001@{candidate.digest}"
    assert task["repo"] == {
        "commit": candidate.base_commit,
        "workdir": "/workspace",
    }
    assert task["visible_tests"] == {
        "command": f"{REBENCH_ENV_PREFIX}python -m pytest -q",
        "ids": [],
    }
    assert task["source"] == {
        "dataset": REBENCH_DATASET,
        "revision": REVISION,
        "instance_id": "acme__widgets-1001",
    }
    proposal = (visible / "openspec" / "changes" / task_id / "proposal.md").read_text(
        encoding="utf-8"
    )
    assert "## Interface" in proposal
    assert "total_widget" in proposal

    verifier = json.loads((hidden / "verifier.json").read_text(encoding="utf-8"))
    assert verifier["framework"] == "pytest"
    assert verifier["timeout_sec"] == 1800
    assert verifier["junit_path"] == "/logs/verifier/junit.xml"
    assert verifier["diff_guard"] == {"forbidden_globs": ["tests/test_widgets.py"]}
    assert json.loads((hidden / "f2p.json").read_text(encoding="utf-8")) == (candidate.fail_to_pass)

    leaked = added_lines(candidate.gold_patch, candidate.test_patch)
    for path in visible.rglob("*"):
        if not path.is_file():
            continue
        lines = {line.strip() for line in path.read_text(encoding="utf-8").splitlines()}
        assert not leaked & lines, path

    generated = to_harbor(visible, tmp_path / "harbor")
    instruction = (generated / "instruction.md").read_text(encoding="utf-8")
    assert "Widget totals are off by one" in instruction


def test_write_task_without_interface_skips_the_section(tmp_path: Path) -> None:
    rows = load_rows(REBENCH)
    selected, _ = select_all(rows)
    candidate = next(item for item in selected if item.instance_id == "acme__widgets-1008")

    task_id = write_task(
        candidate, tmp_path / "store", dataset=REBENCH_DATASET, revision=REVISION, budget=BUDGET
    )

    proposal = (
        tmp_path / "store" / "visible" / task_id / "openspec" / "changes" / task_id / "proposal.md"
    ).read_text(encoding="utf-8")
    assert "## Interface" not in proposal


def test_write_task_validates_against_the_schema(tmp_path: Path) -> None:
    rows = load_rows(REBENCH)
    selected, _ = select_all(rows)

    with pytest.raises(ValueError):
        write_task(
            selected[0],
            tmp_path / "store",
            dataset=REBENCH_DATASET,
            revision=REVISION,
            budget={"usd": 0, "max_turns": 24, "timeout_sec": 600},
        )

    assert not (tmp_path / "store").exists()


def test_workdir_must_be_an_absolute_path(tmp_path: Path) -> None:
    rows = load_rows(REBENCH)
    selected, _ = select_all(rows)

    with pytest.raises(ValueError):
        write_task(
            replace(selected[0], workdir="testbed"),
            tmp_path / "store",
            dataset=REBENCH_DATASET,
            revision=REVISION,
            budget=BUDGET,
        )

    assert not (tmp_path / "store").exists()


def test_manifest_is_stable_and_never_stores_hidden_keys(tmp_path: Path) -> None:
    rows = load_rows(REBENCH)
    selected, _ = select_all(rows)
    entries = [
        {
            "dataset": REBENCH_DATASET,
            "revision": REVISION,
            "instance_id": candidate.instance_id,
            "task_id": candidate.task_id,
            "image": candidate.image,
            "digest": candidate.digest,
        }
        for candidate in reversed(selected)
    ]
    path = tmp_path / "tasks" / "public-v1.manifest.json"

    update_manifest(path, entries)
    first = path.read_bytes()
    update_manifest(path, entries)

    assert path.read_bytes() == first
    document = json.loads(first)
    assert document["schema_version"] == "1"
    assert document["datasets"] == [{"dataset": REBENCH_DATASET, "revision": REVISION}]
    assert [task["instance_id"] for task in document["tasks"]] == sorted(
        candidate.instance_id for candidate in selected
    )
    assert _all_keys(document) & {"patch", "test_patch", "FAIL_TO_PASS", "PASS_TO_PASS"} == set()


def _all_keys(document: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(document, dict):
        for key, value in document.items():
            keys.add(key)
            keys |= _all_keys(value)
    elif isinstance(document, list):
        for value in document:
            keys |= _all_keys(value)
    return keys


def test_load_rows_reads_parquet(tmp_path: Path) -> None:
    rows = load_rows(REBENCH)[:2]
    path = tmp_path / "rows.parquet"
    pq.write_table(pa.Table.from_pylist(rows), path)

    assert load_rows(path) == rows


def test_load_rows_rejects_unknown_formats(tmp_path: Path) -> None:
    path = tmp_path / "rows.csv"
    path.write_text("instance_id\nacme__widgets-1001\n", encoding="utf-8")

    with pytest.raises(ValueError):
        load_rows(path)


@pytest.mark.parametrize("revision", ["main", "0" * 39, "G" * 40, ""])
def test_download_split_requires_a_full_sha(tmp_path: Path, revision: str) -> None:
    with pytest.raises(ValueError):
        download_split("acme/data", revision, "2026_03", tmp_path / "download")


def test_download_split_requests_the_data_dir_shards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict] = []

    def fake_snapshot_download(**kwargs: object) -> None:
        calls.append(dict(kwargs))

    monkeypatch.setattr("factory.tasks.import_hf.snapshot_download", fake_snapshot_download)

    dest = download_split(REBENCH_DATASET, REVISION, "2026_03", tmp_path / "download")

    assert dest == tmp_path / "download"
    assert len(calls) == 1
    assert calls[0]["repo_id"] == REBENCH_DATASET
    assert calls[0]["revision"] == REVISION
    patterns = calls[0]["allow_patterns"]
    assert "data/2026_03-*.parquet" in patterns
    assert "**/2026_03/**" in patterns


def test_load_split_reads_the_data_dir_shard_layout(tmp_path: Path) -> None:
    data = tmp_path / "download" / "data"
    data.mkdir(parents=True)
    shards = {
        "2026_02-00000-of-00001.parquet": ["previous-split"],
        "2026_03-00001-of-00002.parquet": ["second-shard"],
        "2026_03-00000-of-00002.parquet": ["first-shard"],
        "2026_030-00000-of-00001.parquet": ["prefix-lookalike"],
    }
    for name, instance_ids in shards.items():
        table = pa.Table.from_pylist([{"instance_id": value} for value in instance_ids])
        pq.write_table(table, data / name)

    rows = load_split(tmp_path / "download", "2026_03")

    assert [row["instance_id"] for row in rows] == ["first-shard", "second-shard"]
