"""Shared pieces of the trajectory normalizer.

Every format parser turns raw executor output into ``trajectory-event`` objects
(``schemas/trajectory-event.schema.json``). The raw trajectory is archived next
to the normalized one, so events only keep a pointer back to the source record.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

EventKind = Literal[
    "lifecycle", "message", "reasoning", "tool_call", "tool_result", "usage", "error"
]
Role = Literal["system", "user", "assistant", "tool"]
ToolName = Literal["shell", "read", "write", "edit", "search", "web", "other"]

MAX_TEXT_BYTES = 16 * 1024

# Canonical tool names are deliberately coarse: they group the tool names that
# each executor reports into the vocabulary of the schema.
_CANONICAL_TOOLS: dict[str, ToolName] = {
    "bash": "shell",
    "shell": "shell",
    "command_execution": "shell",
    "execute": "shell",
    "terminal": "shell",
    "read": "read",
    "file_read": "read",
    "view": "read",
    "write": "write",
    "create": "write",
    "edit": "edit",
    "multiedit": "edit",
    "notebookedit": "edit",
    "str_replace_editor": "edit",
    "apply_patch": "edit",
    "grep": "search",
    "glob": "search",
    "find": "search",
    "toolsearch": "search",
    "websearch": "web",
    "web_search": "web",
    "webfetch": "web",
    "fetch": "web",
}


def canonical_tool(raw: str | None) -> ToolName | None:
    """Map a tool name as reported by an executor to the schema vocabulary."""
    if raw is None:
        return None
    return _CANONICAL_TOOLS.get(raw.strip().lower(), "other")


def truncate_text(value: Any) -> str | None:
    """Serialize ``value`` as text and cut it to the schema's 16 KiB limit."""
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    encoded = text.encode("utf-8")
    if len(encoded) <= MAX_TEXT_BYTES:
        return text
    return encoded[:MAX_TEXT_BYTES].decode("utf-8", errors="ignore")


def content_text(content: Any) -> str | None:
    """Flatten the string-or-block content shape used by most executors."""
    if content is None:
        return None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)
    return json.dumps(content, ensure_ascii=False)


def token_count(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def token_map(**values: Any) -> dict[str, int] | None:
    """Build the schema's ``tokens`` object, dropping unknown or null counts."""
    mapped = {name: token_count(value) for name, value in values.items()}
    return {name: count for name, count in mapped.items() if count is not None} or None


def tool_input_text(payload: Any) -> str | None:
    """Pick the most informative text of a tool call input."""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        for key in ("command", "cmd", "file_path", "filePath", "path", "pattern", "query", "url"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
    if payload is None:
        return None
    return json.dumps(payload, ensure_ascii=False)


@dataclass
class Event:
    run_id: str
    seq: int
    kind: EventKind
    ts: str | None = None
    role: Role | None = None
    tool: str | None = None
    tool_raw: str | None = None
    text: str | None = None
    exit_code: int | None = None
    tokens: dict[str, int] | None = None
    raw_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "seq": self.seq,
            "ts": self.ts,
            "kind": self.kind,
            "role": self.role,
            "tool": self.tool,
            "tool_raw": self.tool_raw,
            "text": self.text,
            "exit_code": self.exit_code,
            "tokens": self.tokens,
            "raw_ref": self.raw_ref,
        }


class Normalizer:
    """State shared by the format parsers while they walk a raw trajectory."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.events: list[Event] = []
        self.unmapped = 0
        self.skipped_non_json = 0

    def emit(
        self,
        kind: EventKind,
        *,
        ts: str | None = None,
        role: Role | None = None,
        tool: str | None = None,
        tool_raw: str | None = None,
        text: Any = None,
        exit_code: int | None = None,
        tokens: dict[str, int] | None = None,
        raw_ref: str | None = None,
    ) -> Event:
        event = Event(
            run_id=self.run_id,
            seq=len(self.events),
            kind=kind,
            ts=ts,
            role=role,
            tool=tool,
            tool_raw=tool_raw,
            text=truncate_text(text),
            exit_code=exit_code,
            tokens=tokens,
            raw_ref=raw_ref,
        )
        self.events.append(event)
        return event

    def unmapped_record(self, raw_ref: str, raw_type: Any) -> Event:
        """Emit an unknown record as a lifecycle event and count it.

        The raw file is kept, so this never loses the record; the counter is
        what surfaces a format drift after an executor version bump.
        """
        self.unmapped += 1
        label = raw_type if isinstance(raw_type, str) and raw_type else None
        return self.emit("lifecycle", tool_raw=label, text=label, raw_ref=raw_ref)


@dataclass
class Trajectory:
    run_id: str
    format: str
    events: list[Event]
    unmapped: int
    skipped_non_json: int

    def to_dicts(self) -> list[dict[str, Any]]:
        return [event.to_dict() for event in self.events]

    def to_jsonl(self) -> str:
        return "".join(
            json.dumps(document, ensure_ascii=False) + "\n" for document in self.to_dicts()
        )

    def write(self, path: Path) -> None:
        path.write_text(self.to_jsonl(), encoding="utf-8")


def iter_json_records(normalizer: Normalizer, lines: Iterable[str]) -> Iterator[tuple[int, dict]]:
    """Yield ``(line number, object)`` for the JSON-object lines of ``lines``.

    Lines that do not parse as a JSON object (blank lines, log noise mixed into
    stdout) are skipped and counted; they are never mapped and never an error.
    """
    for lineno, line in enumerate(lines, 1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            normalizer.skipped_non_json += 1
            continue
        if not isinstance(record, dict):
            normalizer.skipped_non_json += 1
            continue
        yield lineno, record
