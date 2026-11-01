"""Normalize ``opencode run --format json`` output.

The format is documented as one JSON object per line with ``type``, ``timestamp``
(epoch milliseconds), ``sessionID`` and ``part``; ``tool_use`` carries a part
with a ``tool`` and a ``state``. There is no real sample in the repo yet, so the
sample used by the tests is synthetic and this mapping is unverified against the
real CLI.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .core import (
    Normalizer,
    canonical_tool,
    content_text,
    iter_json_records,
    token_map,
    tool_input_text,
)


def normalize(normalizer: Normalizer, text: str) -> None:
    for lineno, record in iter_json_records(normalizer, text.splitlines()):
        raw_ref = f"line:{lineno}"
        ts = _iso_timestamp(record.get("timestamp"))
        record_type = record.get("type")
        part = record.get("part") if isinstance(record.get("part"), dict) else {}

        if record_type == "step_finish":
            tokens = _usage_tokens(part.get("tokens"))
            if tokens is not None:
                normalizer.emit("usage", ts=ts, tokens=tokens, raw_ref=raw_ref)
            else:
                normalizer.emit("lifecycle", ts=ts, text=record_type, raw_ref=raw_ref)
        elif record_type == "step_start":
            normalizer.emit("lifecycle", ts=ts, text=record_type, raw_ref=raw_ref)
        elif record_type == "text":
            normalizer.emit(
                "message", ts=ts, role="assistant", text=part.get("text"), raw_ref=raw_ref
            )
        elif record_type == "reasoning":
            normalizer.emit(
                "reasoning", ts=ts, role="assistant", text=part.get("text"), raw_ref=raw_ref
            )
        elif record_type == "tool_use":
            _tool_use(normalizer, part, ts, raw_ref)
        elif record_type == "error":
            normalizer.emit("error", ts=ts, text=_error_text(record, part), raw_ref=raw_ref)
        else:
            normalizer.unmapped_record(raw_ref, record_type)


def _tool_use(normalizer: Normalizer, part: dict[str, Any], ts: str | None, raw_ref: str) -> None:
    raw_tool = part.get("tool")
    tool = canonical_tool(raw_tool)
    state = part.get("state") if isinstance(part.get("state"), dict) else {}

    normalizer.emit(
        "tool_call",
        ts=ts,
        role="assistant",
        tool=tool,
        tool_raw=raw_tool,
        text=tool_input_text(state.get("input")),
        raw_ref=raw_ref,
    )

    metadata = state.get("metadata") if isinstance(state.get("metadata"), dict) else {}
    exit_code = state.get("exitCode", metadata.get("exit"))
    normalizer.emit(
        "tool_result",
        ts=ts,
        role="tool",
        tool=tool,
        tool_raw=raw_tool,
        text=content_text(state.get("output")),
        exit_code=exit_code
        if isinstance(exit_code, int) and not isinstance(exit_code, bool)
        else None,
        raw_ref=raw_ref,
    )


def _error_text(record: dict[str, Any], part: dict[str, Any]) -> str | None:
    for candidate in (part.get("message"), record.get("message"), part.get("error")):
        if isinstance(candidate, str):
            return candidate
    return None


def _usage_tokens(tokens: Any) -> dict[str, int] | None:
    if not isinstance(tokens, dict):
        return None
    cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
    return token_map(
        input=tokens.get("input"),
        output=tokens.get("output"),
        cache_read=cache.get("read", tokens.get("cache_read")),
        cache_write=cache.get("write", tokens.get("cache_write")),
        reasoning=tokens.get("reasoning"),
    )


def _iso_timestamp(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return datetime.fromtimestamp(value / 1000, tz=UTC).isoformat().replace("+00:00", "Z")
