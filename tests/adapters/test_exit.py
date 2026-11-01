"""Exit mapping per contract case: done, abort, budget exceeded and error."""

from __future__ import annotations

import pytest

from factory.adapters import (
    ABORT_SPEC_CONFLICT,
    BUDGET_EXCEEDED,
    DONE,
    ERROR,
    map_exit,
)

EXECUTORS = ("claude-code", "codex", "opencode", "mini-swe-agent")
CLAUDE_OK = '{"type": "result", "subtype": "success", "is_error": false}\n'
CODEX_OK = '{"type": "turn.completed"}\n'
OPENCODE_OK = '{"type": "text", "part": {"type": "text", "text": "ok"}}\n'
MINI_OK = {"info": {"exit_status": "Submitted"}}


@pytest.mark.parametrize(
    ("executor", "stream", "trajectory"),
    [
        ("claude-code", CLAUDE_OK, None),
        ("codex", CODEX_OK, None),
        ("opencode", OPENCODE_OK, None),
        ("mini-swe-agent", None, MINI_OK),
    ],
)
def test_exit_done(executor: str, stream: str | None, trajectory: dict | None) -> None:
    decision = map_exit(executor=executor, stream=stream, trajectory=trajectory)
    assert decision.exit == DONE


@pytest.mark.parametrize("executor", EXECUTORS)
def test_exit_abort_has_priority(executor: str) -> None:
    decision = map_exit(
        executor=executor,
        abort={"reason": "spec and tests disagree"},
        stream='{"type": "error"}\n',
        result={"agent_exit_code": 1},
    )
    assert decision.exit == ABORT_SPEC_CONFLICT
    assert decision.detail == "abort.json present"


@pytest.mark.parametrize(
    ("executor", "stream", "trajectory", "result", "gateway_error", "timed_out"),
    [
        (
            "claude-code",
            CLAUDE_OK,
            None,
            None,
            {"type": "budget_exceeded", "status": 429},
            False,
        ),
        (
            "claude-code",
            '{"type": "result", "subtype": "error_max_turns"}\n',
            None,
            None,
            None,
            False,
        ),
        (
            "claude-code",
            '{"type": "result", "subtype": "error_max_budget_usd"}\n',
            None,
            None,
            None,
            False,
        ),
        (
            "mini-swe-agent",
            None,
            {"info": {"exit_status": "LimitsExceeded"}},
            None,
            None,
            False,
        ),
        (
            "codex",
            None,
            None,
            {"exception_info": {"exception_type": "AgentTimeoutError"}},
            None,
            True,
        ),
    ],
)
def test_exit_budget_exceeded(
    executor: str,
    stream: str | None,
    trajectory: dict | None,
    result: dict | None,
    gateway_error: dict | None,
    timed_out: bool,
) -> None:
    decision = map_exit(
        executor=executor,
        stream=stream,
        trajectory=trajectory,
        result=result,
        gateway_error=gateway_error,
        timed_out=timed_out,
    )
    assert decision.exit == BUDGET_EXCEEDED


@pytest.mark.parametrize(
    ("executor", "stream", "trajectory", "result"),
    [
        ("claude-code", '{"type": "result", "subtype": "error_during_execution"}\n', None, None),
        (
            "codex",
            '{"type": "turn.failed"}\n',
            None,
            {
                "exception_info": {
                    "exception_type": "NonZeroAgentExitCodeError",
                    "exception_message": "Command failed (exit 1)",
                }
            },
        ),
        ("opencode", '{"type": "error", "error": {"name": "ProviderError"}}\n', None, None),
        ("mini-swe-agent", None, {"info": {"exit_status": "FormatError"}}, None),
        ("codex", None, None, {"exception_info": {"exception_type": "ApiError"}}),
        ("codex", None, None, {"agent_exit_code": 2}),
        ("codex", None, None, {}),
    ],
)
def test_exit_error(
    executor: str, stream: str | None, trajectory: dict | None, result: dict | None
) -> None:
    decision = map_exit(executor=executor, stream=stream, trajectory=trajectory, result=result)
    assert decision.exit == ERROR


def test_budget_error_is_recognized_by_type_not_status() -> None:
    # Spike B4: a 429 can also be a rate limit, so only error.type decides.
    assert (
        map_exit(
            executor="codex",
            gateway_error={"error": {"type": "budget_exceeded"}, "status": 429},
            stream=CODEX_OK,
        ).exit
        == BUDGET_EXCEEDED
    )
    assert (
        map_exit(
            executor="codex",
            gateway_error={"type": "rate_limit_error", "status": 429},
            stream=CODEX_OK,
        ).exit
        == DONE
    )
