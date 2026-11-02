"""Build and write the ``executor-output`` document (``run.json``).

Every value that the agent could influence is either recomputed on the host (the
diff), taken from the gateway (tokens and cost) or recorded as provenance. The
document is validated against ``schemas/executor-output.schema.json`` before it
reaches disk; an invalid document is never written.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema

from factory.adapters.config import agent_config
from factory.adapters.diff import HostDiff, empty_diff
from factory.adapters.exit import ExitDecision
from factory.adapters.prompt import prompt_sha

HARNESS_VERSION = "0.1.0"
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "executor-output.schema.json"
TOKEN_FIELDS = ("input", "output", "cache_read", "cache_write", "reasoning")

GatewayUsageFn = Callable[[str], Mapping[str, Any]]


class InvalidRunDocument(ValueError):
    """The document does not satisfy the output schema and must not be written."""


@dataclass(frozen=True)
class RunTiming:
    started_at: datetime
    ended_at: datetime


def build_run_document(
    *,
    input_document: Mapping[str, Any],
    exit_decision: ExitDecision,
    diff: HostDiff | None,
    gateway_usage: GatewayUsageFn,
    resolved_model: str,
    image_digest: str,
    timing: RunTiming,
    abort: Mapping[str, Any] | None = None,
    agent_reported_usd: float | None = None,
    raw_uri: str | None = None,
    normalized_uri: str | None = None,
    diff_uri: str | None = None,
) -> dict[str, Any]:
    """Assemble one ``executor-output`` document from host and gateway facts."""
    run_id = input_document["run_id"]
    executor = input_document["executor"]
    config = agent_config(executor["name"])
    alias = input_document["model"]["gateway_alias"]
    usage = gateway_usage(alias)
    tokens = _tokens(usage)
    cost = _cost(usage, agent_reported_usd)
    artifact = diff if diff is not None else empty_diff()

    document: dict[str, Any] = {
        "schema_version": "0.1",
        "run_id": run_id,
        "exit": exit_decision.exit,
        "exit_detail": exit_decision.detail,
        "diff": {
            "uri": diff_uri or f"runs/{run_id}/diff.patch",
            "sha256": artifact.sha256,
            "files_changed": artifact.files_changed,
            "lines_added": artifact.lines_added,
            "lines_removed": artifact.lines_removed,
        },
        "trajectory": {
            "raw_uri": raw_uri or f"trajectories/raw/{run_id}.jsonl",
            "raw_format": config.raw_format,
            "normalized_uri": normalized_uri or f"trajectories/norm/{run_id}.jsonl",
        },
        "tokens": tokens,
        "cost": cost,
        "timing": {
            "started_at": _iso(timing.started_at),
            "ended_at": _iso(timing.ended_at),
            "wall_s": (timing.ended_at - timing.started_at).total_seconds(),
        },
        "abort": dict(abort) if abort is not None else None,
        "provenance": {
            "harness_version": HARNESS_VERSION,
            "executor_name": config.name,
            "executor_version": executor["version"],
            "model_alias": alias,
            "model_resolved": resolved_model,
            "prompt_sha": prompt_sha(),
            "config_sha": executor["config_sha"],
            "task_sha": input_document["task"]["sha256"],
            "image_digest": image_digest,
        },
    }
    validate_run_document(document)
    return document


def validate_run_document(document: Mapping[str, Any]) -> None:
    """Raise ``InvalidRunDocument`` when ``document`` does not match the schema."""
    try:
        _validator().validate(document)
    except jsonschema.ValidationError as exc:
        location = "/".join(str(part) for part in exc.absolute_path) or "(root)"
        raise InvalidRunDocument(f"{location}: {exc.message}") from exc


def write_run_document(document: Mapping[str, Any], path: str | Path) -> Path:
    """Validate and atomically write ``run.json``; never write an invalid document."""
    validate_run_document(document)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2)
            handle.write("\n")
        os.replace(tmp_name, target)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return target


def _tokens(usage: Mapping[str, Any]) -> dict[str, Any]:
    raw = usage.get("tokens")
    if not isinstance(raw, Mapping):
        raise TypeError("gateway_usage must return a 'tokens' mapping")
    tokens: dict[str, Any] = {}
    for field in TOKEN_FIELDS:
        value = raw.get(field)
        if value is None:
            if field in {"input", "output"}:
                raise ValueError(f"gateway_usage is missing '{field}' tokens")
            tokens[field] = None
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"gateway token '{field}' must be a non-negative integer")
        tokens[field] = value
    tokens["source"] = raw.get("source", "gateway")
    return tokens


def _cost(usage: Mapping[str, Any], agent_reported_usd: float | None) -> dict[str, Any]:
    cost: dict[str, Any] = {"source": "gateway"}
    for field in ("usd_real", "usd_shadow"):
        value = usage.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f"gateway_usage '{field}' must be a non-negative number")
        cost[field] = float(value)
    if agent_reported_usd is not None:
        if agent_reported_usd < 0:
            raise ValueError("agent_reported_usd must not be negative")
        cost["agent_reported_usd"] = float(agent_reported_usd)
    else:
        cost["agent_reported_usd"] = None
    return cost


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@lru_cache(maxsize=1)
def _validator() -> jsonschema.Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(schema)
