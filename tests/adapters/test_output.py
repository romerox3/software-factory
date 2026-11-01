"""The output writer: schema validation, gateway cost, reconciliation and prompt hash."""

from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path

import pytest

from factory.adapters import (
    ExitDecision,
    InvalidRunDocument,
    RunTiming,
    build_run_document,
    empty_diff,
    prompt_sha,
    reconcile_cost,
    write_run_document,
)
from factory.adapters.prices import PRICES, expected_usd

from .support import EXAMPLES, load_json

NAMES = ("claude-code", "codex", "opencode", "mini-swe-agent")


def _documents(name: str) -> tuple[dict, dict]:
    return (
        load_json(EXAMPLES / f"{name}.input.json"),
        load_json(EXAMPLES / f"{name}.output.json"),
    )


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _build(name: str, calls: list[str] | None = None) -> tuple[dict, dict]:
    source, example = _documents(name)

    def gateway_usage(alias: str) -> dict:
        if calls is not None:
            calls.append(alias)
        return {
            "tokens": {key: value for key, value in example["tokens"].items() if key != "source"},
            "usd_real": example["cost"]["usd_real"],
            "usd_shadow": example["cost"]["usd_shadow"],
        }

    document = build_run_document(
        input_document=source,
        exit_decision=ExitDecision(example["exit"], example["exit_detail"]),
        diff=empty_diff(),
        gateway_usage=gateway_usage,
        resolved_model=example["provenance"]["model_resolved"],
        image_digest=example["provenance"]["image_digest"],
        timing=RunTiming(
            started_at=_datetime(example["timing"]["started_at"]),
            ended_at=_datetime(example["timing"]["ended_at"]),
        ),
        abort=example.get("abort"),
        agent_reported_usd=example["cost"].get("agent_reported_usd"),
    )
    return source, document


@pytest.mark.parametrize("name", NAMES)
def test_document_matches_the_gateway_and_the_contract(name: str) -> None:
    calls: list[str] = []
    source, document = _build(name, calls)
    example = load_json(EXAMPLES / f"{name}.output.json")

    assert calls == [source["model"]["gateway_alias"]]
    assert document["tokens"] == example["tokens"]
    assert document["cost"] == example["cost"]
    assert document["timing"] == example["timing"]
    assert document["exit"] == example["exit"]
    assert document["trajectory"] == example["trajectory"]
    assert document["provenance"]["prompt_sha"] == prompt_sha()
    assert document["provenance"]["prompt_sha"] != source["prompt"]["sha256"]
    assert document["provenance"]["task_sha"] == source["task"]["sha256"]
    assert document["provenance"]["config_sha"] == source["executor"]["config_sha"]


@pytest.mark.parametrize("name", NAMES)
def test_written_document_is_valid_and_round_trips(name: str, tmp_path: Path) -> None:
    _, document = _build(name)
    path = write_run_document(document, tmp_path / "run.json")

    assert json.loads(path.read_text(encoding="utf-8")) == document


def test_writer_refuses_an_invalid_document(tmp_path: Path) -> None:
    _, document = _build("claude-code")
    invalid = copy.deepcopy(document)
    invalid["exit"] = "abort_spec_conflict"
    invalid["abort"] = None
    target = tmp_path / "run.json"

    with pytest.raises(InvalidRunDocument, match="abort"):
        write_run_document(invalid, target)
    assert not target.exists()


def test_builder_refuses_an_invalid_document_too() -> None:
    source, _ = _documents("claude-code")
    with pytest.raises(InvalidRunDocument):
        build_run_document(
            input_document=source,
            exit_decision=ExitDecision("abort_spec_conflict", "abort.json present"),
            diff=empty_diff(),
            gateway_usage=lambda alias: {
                "tokens": {"input": 1, "output": 1},
                "usd_real": 0.0,
                "usd_shadow": 0.0,
            },
            resolved_model="m",
            image_digest="sha256:" + "a" * 64,
            timing=RunTiming(
                started_at=datetime.fromisoformat("2026-11-03T10:00:00+00:00"),
                ended_at=datetime.fromisoformat("2026-11-03T10:00:01+00:00"),
            ),
        )


def test_missing_gateway_fields_are_rejected() -> None:
    source, _ = _documents("codex")
    with pytest.raises(ValueError, match="usd_real"):
        build_run_document(
            input_document=source,
            exit_decision=ExitDecision("done", "turn.completed"),
            diff=empty_diff(),
            gateway_usage=lambda alias: {
                "tokens": {"input": 1, "output": 1},
                "usd_shadow": 0.0,
            },
            resolved_model="m",
            image_digest="sha256:" + "a" * 64,
            timing=RunTiming(
                started_at=datetime.fromisoformat("2026-11-03T10:00:00+00:00"),
                ended_at=datetime.fromisoformat("2026-11-03T10:00:01+00:00"),
            ),
        )


def test_price_table_uses_list_prices_per_token() -> None:
    assert PRICES["anthropic-sonnet"].cache_read == 2e-7
    assert expected_usd(
        "anthropic-sonnet", {"input": 1_000_000, "output": 100_000}
    ) == pytest.approx(2.0 + 1.0)


def test_reconciliation_flags_more_than_five_percent() -> None:
    within = reconcile_cost("anthropic-sonnet", {"input": 1_000_000}, 2.09, 0.0)
    outside = reconcile_cost("anthropic-sonnet", {"input": 1_000_000}, 2.11, 0.0)
    assert within.expected_usd == pytest.approx(2.0)
    assert within.flagged is False
    assert outside.flagged is True


def test_reconciliation_uses_real_plus_shadow() -> None:
    result = reconcile_cost("anthropic-sonnet", {"input": 1_000_000}, 0.0, 2.11)
    assert result.actual_usd == pytest.approx(2.11)
    assert result.flagged is True


def test_unknown_alias_is_not_flagged() -> None:
    result = reconcile_cost("zai-glm", {"input": 1_000_000}, 10.0, 0.0)
    assert result.expected_usd is None
    assert result.deviation is None
    assert result.flagged is False
