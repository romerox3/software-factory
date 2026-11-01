"""Pytest plugin that reports the result of a run to the verifier over the container's stdout.

This file is *not* imported by the verifier: ``factory.verifier.engine`` copies its source into a
read-only directory under a random module name, mounts it in the container and loads it with
``-p``. It must therefore be self-contained (standard library and pytest only) and must stay
loadable by the oldest Python/pytest that the task images ship.

Why a plugin and not only the JUnit file (docs/05 principle 6, threat T29): the code under test
runs inside the pytest process, so it can rewrite any file pytest wrote, at exit, from the
path it reads in argv. Here the result travels on a stream that is append-only for the
supervisor (it was already copied outside the container when the code under test could try to
retract it) and every line carries a token that this plugin draws at import time, before any
code of the candidate runs. The supervisor ignores unframed output, rejects framed lines with
another token, duplicates, lines after the end and a mismatch between the frames and the
final exit code. A planted tripwire test (a test that always fails; this plugin then reports a
clean exit status when it was the only failure) turns a runner whose failures were turned into
passes into a visible lie.

This does not make the verifier immune to code that patches pytest or this module in-process:
see "Residual risk" in docs/05 and in the F0-12b report.
"""

from __future__ import annotations

import json
import os
import secrets
from typing import Any

import pytest

PREFIX = "FV:"
HELLO_PREFIX = "FVHELLO:"
PROTOCOL = 1

_TOKEN = secrets.token_hex(16)
_TRIPWIRE = "fv_tripwire_" + secrets.token_hex(6)
try:
    _OUT: int | None = os.dup(1)  # taken before the capture plugin replaces fd 1
except OSError:
    _OUT = None
_STATE: dict[str, Any] = {"owner": None, "frames": 0, "ended": False, "other_failures": 0}


def _emit(line: str) -> None:
    if _OUT is None:
        return
    data = ("\n" + line + "\n").encode("utf-8")
    view = memoryview(data)
    while view:
        view = view[os.write(_OUT, view) :]


def _frame(**fields: Any) -> None:
    _emit(PREFIX + _TOKEN + ":" + json.dumps(fields, separators=(",", ":"), sort_keys=True))


# The hello line is the first thing this module does: it runs as the earliest plugin (``-p`` from
# PYTEST_ADDOPTS), before conftest files and before any code of the candidate is imported.
_emit(HELLO_PREFIX + _TOKEN + ":" + json.dumps({"v": PROTOCOL, "tripwire": _TRIPWIRE}))


def _mine(config: Any) -> bool:
    return _STATE["owner"] is not None and _STATE["owner"] is config


class _Tripwire(pytest.Item):
    """A test that always fails; if the verifier sees it pass, failures were turned into passes."""

    def runtest(self) -> None:
        raise AssertionError("tripwire")

    def reportinfo(self) -> tuple[Any, int, str]:
        return (getattr(self, "path", None) or getattr(self, "fspath", ""), 0, self.name)


def pytest_configure(config: Any) -> None:
    # A nested in-process pytest (pytester) must not report on the same stream.
    if _STATE["owner"] is None:
        _STATE["owner"] = config


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(session: Any, config: Any, items: list[Any]) -> None:
    if not _mine(config):
        return
    items.append(_Tripwire.from_parent(session, name=_TRIPWIRE))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item: Any) -> Any:
    _STATE["current"] = item.config
    yield
    _STATE["current"] = None


def pytest_runtest_logreport(report: Any) -> None:
    owner = _STATE["owner"]
    if owner is None or _STATE.get("current") is not owner or _STATE["ended"]:
        return
    _STATE["frames"] += 1
    if report.failed and not hasattr(report, "wasxfail") and not report.nodeid.endswith(_TRIPWIRE):
        _STATE["other_failures"] += 1
    _frame(
        t="r",
        id=report.nodeid,
        when=report.when,
        o=report.outcome,
        x=hasattr(report, "wasxfail"),
    )


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: Any, exitstatus: Any) -> None:
    if not _mine(session.config) or _STATE["ended"]:
        return
    _STATE["ended"] = True
    status = int(exitstatus)
    if status == int(pytest.ExitCode.TESTS_FAILED) and _STATE["other_failures"] == 0:
        # The tripwire is the only failure: the run is clean, and the process must say so.
        status = int(pytest.ExitCode.OK)
        session.exitstatus = pytest.ExitCode.OK
    _frame(t="end", exit=status, frames=_STATE["frames"])
