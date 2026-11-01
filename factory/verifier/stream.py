"""Parse the result stream that ``runner_plugin`` writes to the container's stdout.

The stream is the primary source of truth for pytest tasks (docs/05 principle 6, threat T29).
Rules that make a forgery visible instead of silently accepted:

* exactly one ``FVHELLO:<token>:<json>`` line, before any frame; the token is drawn by the plugin
  when it is imported, before any code of the candidate runs;
* every ``FV:`` line carries that token and valid JSON, otherwise it is a forgery (the code under
  test wrote framed output it could not have been given);
* no duplicate ``(id, when)`` frame, a single ``end`` frame, nothing framed after it, and an
  ``end`` whose frame count equals the frames seen;
* the tripwire test (a test that always fails) must have failed; if it passed, failures were
  turned into passes. A clean run (exit status 0) must contain it.

Output without the frame prefix is ignored (pytest's own progress, prints of the tests).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

HELLO_PREFIX = b"FVHELLO:"
FRAME_PREFIX = b"FV:"
PHASES = ("setup", "call", "teardown")
OUTCOMES = frozenset({"passed", "failed", "skipped"})
TOKEN_LENGTH = 32
# The verdict schema only knows the statuses of the JUnit parser; an expected failure is a skip
# and a test that never completed is an error. Neither is ever ``passed``.
_PUBLIC = {"xfailed": "skipped", "incomplete": "error"}

# Problems that mean the code under test (or the run) tampered with the stream.
FORGED = "forged"
# Problems that mean there is no usable stream (the run ended or died without sealing it).
MISSING = "missing"
TRUNCATED = "truncated"


@dataclass(frozen=True)
class StreamReport:
    """What the stream says. ``problem`` is ``None`` only when the stream is complete and clean."""

    statuses: dict[str, str] = field(default_factory=dict)
    exit_status: int | None = None
    problem: str | None = None
    detail: str = ""

    @property
    def forged(self) -> bool:
        return self.problem == FORGED


def parse_stream(stdout: bytes, *, truncated: bool = False) -> StreamReport:
    """Turn the container's stdout into per-test statuses, or say what is wrong with it."""
    try:
        return _parse(stdout, truncated)
    except _Bad as bad:
        return StreamReport(problem=bad.kind, detail=str(bad))


class _Bad(Exception):
    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(detail)
        self.kind = kind


def _forged(detail: str) -> _Bad:
    return _Bad(FORGED, detail)


def _parse(stdout: bytes, truncated: bool) -> StreamReport:
    token: bytes | None = None
    tripwire = ""
    phases: dict[str, dict[str, tuple[str, bool]]] = {}
    frames = 0
    end: dict[str, Any] | None = None

    for raw in stdout.split(b"\n"):
        line = raw.rstrip(b"\r")
        if line.startswith(HELLO_PREFIX):
            if token is not None:
                raise _forged("second hello")
            token, tripwire = _read_hello(line)
            continue
        if not line.startswith(FRAME_PREFIX):
            continue
        if token is None:
            raise _forged("frame before the hello")
        body = _read_frame(line, token)
        if end is not None:
            raise _forged("frame after the end")
        kind = body.get("t")
        if kind == "end":
            end = body
        elif kind == "r":
            frames += 1
            _add_report(phases, body)
        else:
            raise _forged("unknown frame type")

    if token is None:
        raise _Bad(MISSING, "no hello: the plugin did not run")
    if truncated:
        raise _Bad(TRUNCATED, "the stream is larger than the limit")
    if end is None:
        raise _Bad(MISSING, "no end frame: the run did not finish")
    exit_status = end.get("exit")
    if not isinstance(exit_status, int) or isinstance(exit_status, bool):
        raise _forged("end frame without an integer exit status")
    if end.get("frames") != frames:
        raise _forged("end frame disagrees with the frames seen")

    statuses = {test_id: _status(parts) for test_id, parts in phases.items()}
    wire = statuses.pop("::" + tripwire, None)
    if wire is not None and wire != "failed":
        raise _forged("the tripwire test did not fail")
    if wire is None and exit_status == 0:
        raise _forged("a clean run is missing the tripwire test")
    public = {test_id: _PUBLIC.get(status, status) for test_id, status in statuses.items()}
    return StreamReport(statuses=public, exit_status=exit_status)


def _read_hello(line: bytes) -> tuple[bytes, str]:
    _, _, rest = line.partition(b":")
    token, separator, payload = rest.partition(b":")
    if not separator or len(token) != TOKEN_LENGTH or not _is_hex(token):
        raise _forged("malformed hello")
    document = _json(payload)
    tripwire = document.get("tripwire")
    if document.get("v") != 1 or not isinstance(tripwire, str) or not tripwire:
        raise _forged("malformed hello")
    return token, tripwire


def _read_frame(line: bytes, token: bytes) -> dict[str, Any]:
    _, _, rest = line.partition(b":")
    given, separator, payload = rest.partition(b":")
    if not separator or given != token:
        raise _forged("framed line with another token")
    return _json(payload)


def _json(payload: bytes) -> dict[str, Any]:
    try:
        document = json.loads(payload)
    except ValueError as exc:
        raise _forged("framed line that is not JSON") from exc
    if not isinstance(document, dict):
        raise _forged("framed line that is not an object")
    return document


def _is_hex(data: bytes) -> bool:
    return all(byte in b"0123456789abcdef" for byte in data)


def _add_report(phases: dict[str, dict[str, tuple[str, bool]]], body: dict[str, Any]) -> None:
    test_id, when, outcome, expected_failure = (
        body.get("id"),
        body.get("when"),
        body.get("o"),
        body.get("x"),
    )
    if (
        not isinstance(test_id, str)
        or when not in PHASES
        or outcome not in OUTCOMES
        or not isinstance(expected_failure, bool)
    ):
        raise _forged("malformed report frame")
    parts = phases.setdefault(test_id, {})
    if when in parts:
        raise _forged("the same phase of a test was reported twice")
    parts[when] = (outcome, expected_failure)


def _status(parts: dict[str, tuple[str, bool]]) -> str:
    """Same precedence as the JUnit writer: error, failed, skipped, passed.

    ``xfailed`` is an expected failure (it never counts as passed); a test whose call phase
    never ran (the process died, or setup did not pass) is ``incomplete`` unless setup skipped it.
    """
    setup = parts.get("setup")
    call = parts.get("call")
    teardown = parts.get("teardown")
    if setup is None:
        return "incomplete"
    if "failed" in (setup[0], teardown[0] if teardown else "passed"):
        return "error"
    if setup[0] == "skipped":
        return "skipped"
    if call is None:
        return "incomplete"
    if call[0] == "failed":
        return "failed"
    if teardown is None:
        return "incomplete"
    if call[0] == "skipped":
        return "xfailed" if call[1] else "skipped"
    return "passed"
