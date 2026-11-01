"""Map one Harbor run to the four ``exit`` values of the executor contract.

Inputs are the trial's ``result.json`` (``exception_info`` and the agent exit
code) plus the gateway's budget error. The copied CLI stream is used for the
cases the contract describes per adapter (Claude ``subtype``, Codex turn events,
OpenCode's ``error`` event and mini-swe-agent's ``info.exit_status``).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

DONE = "done"
ABORT_SPEC_CONFLICT = "abort_spec_conflict"
BUDGET_EXCEEDED = "budget_exceeded"
ERROR = "error"

BUDGET_EXCEPTIONS = frozenset({"AgentTimeoutError", "BudgetExceededError"})
EXIT_CODE = re.compile(r"\(exit (-?\d+)\)")


@dataclass(frozen=True)
class ExitDecision:
    exit: str
    detail: str


def map_exit(
    *,
    executor: str,
    abort: Mapping[str, Any] | None = None,
    result: Mapping[str, Any] | None = None,
    gateway_error: Mapping[str, Any] | str | None = None,
    timed_out: bool = False,
    stream: bytes | str | None = None,
    trajectory: Mapping[str, Any] | None = None,
    agent_exit_code: int | None = None,
) -> ExitDecision:
    """Classify one attempt. ``abort.json`` has priority over every other signal."""
    if abort is not None:
        return ExitDecision(ABORT_SPEC_CONFLICT, "abort.json present")
    if _is_budget_error(gateway_error):
        return ExitDecision(BUDGET_EXCEEDED, "gateway budget rejected (error.type=budget_exceeded)")

    exception_type = _exception_type(result)
    if timed_out or exception_type in BUDGET_EXCEPTIONS:
        detail = "wall-clock limit" if timed_out else f"exception_type={exception_type}"
        return ExitDecision(BUDGET_EXCEEDED, detail)

    stream_decision = _stream_decision(executor, stream, trajectory)
    if stream_decision is not None and stream_decision.exit == BUDGET_EXCEEDED:
        return stream_decision

    if exception_type:
        return ExitDecision(ERROR, f"exception_type={exception_type}")

    if stream_decision is not None:
        return stream_decision

    code = _agent_exit_code(result, agent_exit_code)
    if code is not None:
        return ExitDecision(DONE if code == 0 else ERROR, f"agent exit code {code}")
    return ExitDecision(ERROR, "no agent outcome in result.json")


def _is_budget_error(error: Mapping[str, Any] | str | None) -> bool:
    if isinstance(error, str):
        return error == "budget_exceeded"
    if not isinstance(error, Mapping):
        return False
    candidates = [error.get("type"), error.get("error_type")]
    inner = error.get("error")
    if isinstance(inner, Mapping):
        candidates.append(inner.get("type"))
    return any(candidate == "budget_exceeded" for candidate in candidates)


def _exception_type(result: Mapping[str, Any] | None) -> str:
    if not isinstance(result, Mapping):
        return ""
    info = result.get("exception_info")
    if not isinstance(info, Mapping):
        return ""
    value = info.get("exception_type")
    return value if isinstance(value, str) else ""


def _agent_exit_code(result: Mapping[str, Any] | None, explicit: int | None) -> int | None:
    if explicit is not None:
        return explicit
    if not isinstance(result, Mapping):
        return None
    for key in ("agent_exit_code", "exit_code"):
        value = result.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    agent_result = result.get("agent_result")
    if isinstance(agent_result, Mapping):
        value = agent_result.get("exit_code")
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    info = result.get("exception_info")
    if isinstance(info, Mapping):
        message = info.get("exception_message")
        if isinstance(message, str):
            match = EXIT_CODE.search(message)
            if match:
                return int(match.group(1))
    return None


def _json_lines(stream: bytes | str | None) -> Iterator[Mapping[str, Any]]:
    if stream is None:
        return
    text = stream.decode("utf-8", "replace") if isinstance(stream, bytes) else stream
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, Mapping):
            yield event


def _stream_decision(
    executor: str, stream: bytes | str | None, trajectory: Mapping[str, Any] | None
) -> ExitDecision | None:
    if executor == "claude-code":
        return _claude_decision(stream)
    if executor == "codex":
        return _codex_decision(stream)
    if executor == "opencode":
        return _opencode_decision(stream)
    if executor == "mini-swe-agent":
        return _mini_decision(trajectory)
    return None


def _claude_decision(stream: bytes | str | None) -> ExitDecision | None:
    last: Mapping[str, Any] | None = None
    for event in _json_lines(stream):
        if event.get("type") == "result":
            last = event
    if last is None:
        return None
    subtype = last.get("subtype")
    detail = f"subtype={subtype}" if isinstance(subtype, str) else "result"
    if subtype == "success" and not last.get("is_error"):
        return ExitDecision(DONE, detail)
    if subtype in {"error_max_turns", "error_max_budget_usd"}:
        return ExitDecision(BUDGET_EXCEEDED, detail)
    return ExitDecision(ERROR, detail)


def _codex_decision(stream: bytes | str | None) -> ExitDecision | None:
    completed = failed = False
    for event in _json_lines(stream):
        kind = event.get("type")
        if kind == "turn.completed" and not event.get("error"):
            completed = True
        elif kind in {"turn.failed", "error"}:
            failed = True
    if failed:
        return ExitDecision(ERROR, "turn.failed or error event")
    if completed:
        return ExitDecision(DONE, "turn.completed")
    return None


def _opencode_decision(stream: bytes | str | None) -> ExitDecision | None:
    seen = False
    for event in _json_lines(stream):
        seen = True
        if event.get("type") == "error":
            return ExitDecision(ERROR, "error event")
    if seen:
        return ExitDecision(DONE, "finished without error event")
    return None


def _mini_decision(trajectory: Mapping[str, Any] | None) -> ExitDecision | None:
    if not isinstance(trajectory, Mapping):
        return None
    info = trajectory.get("info")
    if not isinstance(info, Mapping):
        return None
    status = info.get("exit_status")
    if not isinstance(status, str) or not status.strip():
        return None
    normalized = status.strip().lower()
    detail = f"exit_status={status}"
    if normalized in {"submitted", "done", "success"}:
        return ExitDecision(DONE, detail)
    if any(token in normalized for token in ("limit", "budget", "cost", "timeout", "step")):
        return ExitDecision(BUDGET_EXCEEDED, detail)
    return ExitDecision(ERROR, detail)
