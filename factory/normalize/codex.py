"""Normalize ``codex exec --json`` output.

In production Codex's stdout can arrive mixed with stderr log lines. Anything
that is not a JSON object is counted as ``skipped_non_json``; it is never an
error and it never maps to an event.
"""

from __future__ import annotations

from typing import Any

from .core import Normalizer, iter_json_records, token_map, tool_input_text


def normalize(normalizer: Normalizer, text: str) -> None:
    for lineno, record in iter_json_records(normalizer, text.splitlines()):
        raw_ref = f"line:{lineno}"
        record_type = record.get("type")

        if record_type in ("thread.started", "turn.started"):
            normalizer.emit("lifecycle", text=record_type, raw_ref=raw_ref)
        elif record_type in ("item.started", "item.completed"):
            item = record.get("item")
            if not isinstance(item, dict):
                normalizer.unmapped_record(raw_ref, record_type)
                continue
            _item(normalizer, record_type, item, raw_ref)
        elif record_type == "turn.completed":
            tokens = _usage_tokens(record.get("usage"))
            if tokens is None:
                normalizer.emit("lifecycle", text=record_type, raw_ref=raw_ref)
            else:
                normalizer.emit("usage", tokens=tokens, raw_ref=raw_ref)
        elif record_type in ("turn.failed", "error"):
            normalizer.emit("error", text=_error_text(record), raw_ref=raw_ref)
        else:
            normalizer.unmapped_record(raw_ref, record_type)


def _item(
    normalizer: Normalizer,
    record_type: str,
    item: dict[str, Any],
    raw_ref: str,
) -> None:
    item_type = item.get("type")

    if item_type == "command_execution":
        if record_type == "item.started":
            normalizer.emit(
                "tool_call",
                role="assistant",
                tool="shell",
                tool_raw=item_type,
                text=tool_input_text(item.get("command")),
                raw_ref=raw_ref,
            )
        else:
            normalizer.emit(
                "tool_result",
                role="tool",
                tool="shell",
                tool_raw=item_type,
                text=item.get("aggregated_output"),
                exit_code=_exit_code(item.get("exit_code")),
                raw_ref=raw_ref,
            )
    elif item_type == "reasoning":
        normalizer.emit("reasoning", role="assistant", text=item.get("text"), raw_ref=raw_ref)
    elif item_type == "agent_message":
        normalizer.emit("message", role="assistant", text=item.get("text"), raw_ref=raw_ref)
    elif item_type == "error":
        normalizer.emit("error", text=item.get("message"), raw_ref=raw_ref)
    else:
        normalizer.unmapped_record(raw_ref, item_type)


def _error_text(record: dict[str, Any]) -> str | None:
    error = record.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str):
            return message
    if isinstance(error, str):
        return error
    message = record.get("message")
    return message if isinstance(message, str) else None


def _exit_code(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _usage_tokens(usage: Any) -> dict[str, int] | None:
    if not isinstance(usage, dict):
        return None
    return token_map(
        input=usage.get("input_tokens"),
        output=usage.get("output_tokens"),
        cache_read=usage.get("cached_input_tokens"),
        cache_write=usage.get("cache_write_input_tokens"),
        reasoning=usage.get("reasoning_output_tokens"),
    )
