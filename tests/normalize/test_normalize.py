"""Tests for the raw-trajectory normalizer."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from factory.normalize import cli, normalize_text
from factory.normalize.core import Event, Trajectory

REPO_ROOT = Path(__file__).parents[2]
SAMPLES_DIR = Path(__file__).parent / "samples"
TRAJECTORY_SCHEMA = json.loads(
    (REPO_ROOT / "schemas" / "trajectory-event.schema.json").read_text(encoding="utf-8")
)
VALIDATOR = jsonschema.Draft202012Validator(TRAJECTORY_SCHEMA)

SAMPLES = [
    ("claude-code", "claude-code-2.1.316.stream.jsonl"),
    ("codex", "codex-0.166.0.exec.jsonl"),
    ("opencode", "opencode-run-1.19.5.synthetic.jsonl"),
    ("mini-swe-agent", "mini-swe-agent-2.4.6.traj.synthetic.json"),
]
EXPECTED_TOOL_CALLS = {
    "claude-code": 4,
    "codex": 6,
    "opencode": 2,
    "mini-swe-agent": 2,
}


def load_sample(fmt: str, filename: str) -> Trajectory:
    text = (SAMPLES_DIR / filename).read_text(encoding="utf-8")
    return normalize_text(fmt, "run-test", text)


def sample_ids() -> list[str]:
    return [filename for _, filename in SAMPLES]


@pytest.mark.parametrize(("fmt", "filename"), SAMPLES, ids=sample_ids())
def test_every_event_validates_against_the_schema(fmt: str, filename: str) -> None:
    trajectory = load_sample(fmt, filename)
    assert trajectory.events
    for event in trajectory.events:
        VALIDATOR.validate(event.to_dict())


@pytest.mark.parametrize(("fmt", "filename"), SAMPLES, ids=sample_ids())
def test_seq_is_contiguous_from_zero(fmt: str, filename: str) -> None:
    trajectory = load_sample(fmt, filename)
    assert [event.seq for event in trajectory.events] == list(range(len(trajectory.events)))


@pytest.mark.parametrize(("fmt", "filename"), SAMPLES, ids=sample_ids())
def test_every_event_carries_the_run_id(fmt: str, filename: str) -> None:
    trajectory = load_sample(fmt, filename)
    assert {event.run_id for event in trajectory.events} == {"run-test"}


@pytest.mark.parametrize(("fmt", "filename"), SAMPLES, ids=sample_ids())
def test_samples_have_no_unmapped_records(fmt: str, filename: str) -> None:
    trajectory = load_sample(fmt, filename)
    assert trajectory.unmapped == 0
    assert trajectory.skipped_non_json == 0


@pytest.mark.parametrize(("fmt", "filename"), SAMPLES, ids=sample_ids())
def test_tool_calls_and_results_pair_up(fmt: str, filename: str) -> None:
    trajectory = load_sample(fmt, filename)
    calls = [event for event in trajectory.events if event.kind == "tool_call"]
    results = [event for event in trajectory.events if event.kind == "tool_result"]

    assert len(calls) == EXPECTED_TOOL_CALLS[fmt]
    assert len(calls) == len(results)
    for call, result in zip(calls, results, strict=True):
        assert result.tool == call.tool
        assert result.tool_raw == call.tool_raw


@pytest.mark.parametrize(("fmt", "filename"), SAMPLES, ids=sample_ids())
def test_raw_ref_points_back_to_the_source_record(fmt: str, filename: str) -> None:
    trajectory = load_sample(fmt, filename)
    prefix = "messages:" if fmt == "mini-swe-agent" else "line:"
    assert all(event.raw_ref and event.raw_ref.startswith(prefix) for event in trajectory.events)


def test_codex_skips_interleaved_non_json_lines() -> None:
    sample = SAMPLES_DIR / "codex-0.166.0.exec.jsonl"
    lines = sample.read_text(encoding="utf-8").splitlines()
    mixed = []
    for index, line in enumerate(lines):
        mixed.append(f"2026-11-01T10:00:{index % 60:02d}Z WARN codex stderr log line {index}")
        mixed.append(line)

    baseline = normalize_text("codex", "run-test", "\n".join(lines))
    trajectory = normalize_text("codex", "run-test", "\n".join(mixed))

    assert trajectory.skipped_non_json == len(lines)
    assert trajectory.unmapped == 0
    assert len(trajectory.events) == len(baseline.events)

    def shape(events: list[Event]) -> list[tuple[str, str | None, str | None, str | None]]:
        return [(event.kind, event.tool, event.tool_raw, event.text) for event in events]

    assert shape(trajectory.events) == shape(baseline.events)
    for event in trajectory.events:
        VALIDATOR.validate(event.to_dict())


def test_unknown_record_is_counted_and_kept_as_lifecycle() -> None:
    trajectory = normalize_text("codex", "run-test", '{"type":"brand.new","payload":{}}\n')
    assert trajectory.unmapped == 1
    assert len(trajectory.events) == 1
    event = trajectory.events[0]
    assert event.kind == "lifecycle"
    assert event.tool_raw == "brand.new"


def test_claude_result_tokens() -> None:
    trajectory = load_sample("claude-code", "claude-code-2.1.316.stream.jsonl")
    usage = [event for event in trajectory.events if event.kind == "usage"]
    assert len(usage) == 1
    assert usage[0].tokens == {
        "input": 6,
        "output": 686,
        "cache_read": 33667,
        "cache_write": 17553,
        "reasoning": 0,
    }


def test_codex_turn_tokens() -> None:
    trajectory = load_sample("codex", "codex-0.166.0.exec.jsonl")
    usage = [event for event in trajectory.events if event.kind == "usage"]
    assert len(usage) == 1
    assert usage[0].tokens == {
        "input": 40719,
        "output": 3132,
        "cache_read": 6784,
        "cache_write": 0,
        "reasoning": 1443,
    }


def test_cli_writes_valid_jsonl_and_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "trajectory.jsonl"
    sample = SAMPLES_DIR / "codex-0.166.0.exec.jsonl"

    code = cli.main(["--format", "codex", "--run-id", "run-cli", str(sample), "-o", str(output)])

    assert code == 0
    lines = output.read_text(encoding="utf-8").splitlines()
    assert lines
    for line in lines:
        VALIDATOR.validate(json.loads(line))
    summary = capsys.readouterr().out.strip()
    assert summary == (
        "format=codex run_id=run-cli events=30 unmapped=0 skipped_non_json=0 invalid=0"
    )


def test_cli_exits_one_on_an_invalid_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    invalid = Trajectory(
        run_id="run-bad",
        format="codex",
        events=[Event(run_id="run-bad", seq=0, kind="not-a-kind")],
        unmapped=0,
        skipped_non_json=0,
    )
    monkeypatch.setattr(cli, "normalize_text", lambda *args, **kwargs: invalid)
    output = tmp_path / "trajectory.jsonl"
    sample = SAMPLES_DIR / "codex-0.166.0.exec.jsonl"

    code = cli.main(["--format", "codex", "--run-id", "run-bad", str(sample), "-o", str(output)])

    assert code == 1
    assert not output.exists()
