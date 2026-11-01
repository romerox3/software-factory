"""Normalize mini-swe-agent ``.traj.json`` files (``mini-swe-agent-1.1``).

The trajectory is one JSON document with ``messages[]`` and ``info``. Assistant
messages carry the bash action either as fenced blocks in ``content`` or as
``extra.actions``; the following user/tool message is its observation. There is
no real sample in the repo yet, so the sample used by the tests is synthetic and
this mapping is unverified against a real trajectory.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .core import Normalizer, content_text, token_map

_ACTION_BLOCK = re.compile(r"```(?:bash|sh|shell)?\s*\n(.*?)```", re.DOTALL)


def normalize(normalizer: Normalizer, text: str) -> None:
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"mini-swe-agent trajectory is not valid JSON: {exc}") from exc
    messages = document.get("messages") if isinstance(document, dict) else None
    if not isinstance(messages, list):
        raise TypeError("mini-swe-agent trajectory has no messages[]")

    pending: list[str] = []

    for index, message in enumerate(messages):
        raw_ref = f"messages:{index}"
        if not isinstance(message, dict):
            normalizer.unmapped_record(raw_ref, "message")
            continue
        role = message.get("role")
        if role == "system":
            normalizer.emit(
                "message", role="system", text=content_text(message.get("content")), raw_ref=raw_ref
            )
        elif role == "assistant":
            pending = _assistant(normalizer, message, raw_ref)
        elif role in ("user", "tool"):
            _observation(normalizer, message, raw_ref, pending, role)
        else:
            normalizer.unmapped_record(raw_ref, role)


def _assistant(normalizer: Normalizer, message: dict[str, Any], raw_ref: str) -> list[str]:
    content = content_text(message.get("content")) or ""
    thought = _ACTION_BLOCK.sub("", content).strip()
    actions = _declared_actions(message.get("extra"))
    if not actions:
        actions = [block.strip() for block in _ACTION_BLOCK.findall(content) if block.strip()]

    if actions:
        if thought:
            normalizer.emit("reasoning", role="assistant", text=thought, raw_ref=raw_ref)
        for command in actions:
            normalizer.emit(
                "tool_call",
                role="assistant",
                tool="shell",
                tool_raw="bash",
                text=command,
                raw_ref=raw_ref,
            )
    else:
        normalizer.emit("message", role="assistant", text=content, raw_ref=raw_ref)

    extra = message.get("extra") if isinstance(message.get("extra"), dict) else {}
    response = extra.get("response") if isinstance(extra.get("response"), dict) else {}
    tokens = _usage_tokens(response.get("usage"))
    if tokens is not None:
        normalizer.emit("usage", tokens=tokens, raw_ref=raw_ref)

    return actions


def _observation(
    normalizer: Normalizer,
    message: dict[str, Any],
    raw_ref: str,
    pending: list[str],
    role: str,
) -> None:
    text = content_text(message.get("content"))
    if pending or role == "tool":
        tool = "shell" if pending else None
        if pending:
            pending.pop(0)
        normalizer.emit(
            "tool_result",
            role="tool",
            tool=tool,
            tool_raw="bash" if tool else None,
            text=text,
            raw_ref=raw_ref,
        )
    else:
        normalizer.emit("message", role="user", text=text, raw_ref=raw_ref)


def _declared_actions(extra: Any) -> list[str]:
    if not isinstance(extra, dict) or not isinstance(extra.get("actions"), list):
        return []
    actions = []
    for action in extra["actions"]:
        if isinstance(action, str):
            actions.append(action)
        elif isinstance(action, dict):
            command = action.get("command") or action.get("cmd")
            if isinstance(command, str) and command:
                actions.append(command)
    return actions


def _usage_tokens(usage: Any) -> dict[str, int] | None:
    if not isinstance(usage, dict):
        return None
    prompt_details = usage.get("prompt_tokens_details")
    completion_details = usage.get("completion_tokens_details")
    cache_read = usage.get("cache_read_input_tokens")
    if cache_read is None and isinstance(prompt_details, dict):
        cache_read = prompt_details.get("cached_tokens")
    reasoning = usage.get("reasoning_tokens")
    if reasoning is None and isinstance(completion_details, dict):
        reasoning = completion_details.get("reasoning_tokens")
    return token_map(
        input=usage.get("input_tokens", usage.get("prompt_tokens")),
        output=usage.get("output_tokens", usage.get("completion_tokens")),
        cache_read=cache_read,
        cache_write=usage.get("cache_creation_input_tokens"),
        reasoning=reasoning,
    )
