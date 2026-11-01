"""Normalize ``claude -p --output-format stream-json --verbose`` output."""

from __future__ import annotations

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
    # tool_use id -> (canonical tool, raw tool) so tool_result lines inherit the
    # name of the call they answer.
    pending: dict[str, tuple[str | None, str | None]] = {}

    for lineno, record in iter_json_records(normalizer, text.splitlines()):
        raw_ref = f"line:{lineno}"
        ts = record.get("timestamp")
        record_type = record.get("type")

        if record_type == "system":
            normalizer.emit(
                "lifecycle", ts=ts, text=record.get("subtype") or "system", raw_ref=raw_ref
            )
        elif record_type == "assistant":
            _assistant(normalizer, record, ts, raw_ref, pending)
        elif record_type == "user":
            _user(normalizer, record, ts, raw_ref, pending)
        elif record_type == "result":
            normalizer.emit(
                "usage", ts=ts, tokens=_usage_tokens(record.get("usage")), raw_ref=raw_ref
            )
            normalizer.emit(
                "lifecycle", ts=ts, text=record.get("subtype") or "result", raw_ref=raw_ref
            )
        else:
            normalizer.unmapped_record(raw_ref, record_type)


def _assistant(
    normalizer: Normalizer,
    record: dict[str, Any],
    ts: str | None,
    raw_ref: str,
    pending: dict[str, tuple[str | None, str | None]],
) -> None:
    message = record.get("message") or {}
    content = message.get("content")
    if not isinstance(content, list):
        normalizer.emit(
            "message", ts=ts, role="assistant", text=content_text(content), raw_ref=raw_ref
        )
        return

    for block in content:
        if not isinstance(block, dict):
            normalizer.unmapped_record(raw_ref, "assistant_block")
            continue
        block_type = block.get("type")
        if block_type == "text":
            normalizer.emit(
                "message", ts=ts, role="assistant", text=block.get("text"), raw_ref=raw_ref
            )
        elif block_type == "thinking":
            normalizer.emit(
                "reasoning", ts=ts, role="assistant", text=block.get("thinking"), raw_ref=raw_ref
            )
        elif block_type == "tool_use":
            raw_tool = block.get("name")
            tool = canonical_tool(raw_tool)
            tool_id = block.get("id")
            if isinstance(tool_id, str):
                pending[tool_id] = (tool, raw_tool)
            normalizer.emit(
                "tool_call",
                ts=ts,
                role="assistant",
                tool=tool,
                tool_raw=raw_tool,
                text=tool_input_text(block.get("input")),
                raw_ref=raw_ref,
            )
        else:
            normalizer.unmapped_record(raw_ref, block_type)


def _user(
    normalizer: Normalizer,
    record: dict[str, Any],
    ts: str | None,
    raw_ref: str,
    pending: dict[str, tuple[str | None, str | None]],
) -> None:
    message = record.get("message") or {}
    content = message.get("content")
    if not isinstance(content, list):
        normalizer.emit("message", ts=ts, role="user", text=content_text(content), raw_ref=raw_ref)
        return

    for block in content:
        if not isinstance(block, dict):
            normalizer.unmapped_record(raw_ref, "user_block")
            continue
        block_type = block.get("type")
        if block_type == "tool_result":
            tool, raw_tool = pending.pop(block.get("tool_use_id"), (None, None))
            normalizer.emit(
                "tool_result",
                ts=ts,
                role="tool",
                tool=tool,
                tool_raw=raw_tool,
                text=content_text(block.get("content")),
                raw_ref=raw_ref,
            )
        elif block_type == "text":
            normalizer.emit("message", ts=ts, role="user", text=block.get("text"), raw_ref=raw_ref)
        else:
            normalizer.unmapped_record(raw_ref, block_type)


def _usage_tokens(usage: Any) -> dict[str, int] | None:
    if not isinstance(usage, dict):
        return None
    details = usage.get("output_tokens_details")
    reasoning = details.get("thinking_tokens") if isinstance(details, dict) else None
    return token_map(
        input=usage.get("input_tokens"),
        output=usage.get("output_tokens"),
        cache_read=usage.get("cache_read_input_tokens"),
        cache_write=usage.get("cache_creation_input_tokens"),
        reasoning=reasoning,
    )
