"""Parse JUnit XML reports produced by pytest, jest-junit and vitest.

The report is untrusted input: the parser only uses ``defusedxml`` and rejects
oversized files before handing them to the XML parser.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from defusedxml import ElementTree

if TYPE_CHECKING:
    from xml.etree.ElementTree import Element

Status = Literal["passed", "failed", "error", "skipped"]

MAX_REPORT_BYTES = 50 * 1024 * 1024

_ROOT_TAGS = frozenset({"testsuites", "testsuite"})

# Ordered from strongest to weakest: the first matching child wins.
_STATUS_PRECEDENCE: tuple[tuple[str, Status], ...] = (
    ("error", "error"),
    ("failure", "failed"),
    ("skipped", "skipped"),
)

# Ordered from worst to best: merging repeated ids keeps the worst status.
_STATUS_RANK: dict[Status, int] = {"passed": 0, "skipped": 1, "failed": 2, "error": 3}

_WHITESPACE = re.compile(r"\s+")


def parse_junit(path: Path, *, merge_duplicates: bool = False) -> dict[str, Status]:
    """Return the status of every ``<testcase>`` in the JUnit report at ``path``.

    Raises ``ValueError`` for reports larger than ``MAX_REPORT_BYTES`` or, unless
    ``merge_duplicates`` is set, for reports that repeat a test id. With merging,
    a repeated id keeps its worst status so an extra passing copy can never hide
    a failing one. Malicious XML (DTDs, entities) raises the exception from
    ``defusedxml``.
    """
    size = path.stat().st_size
    if size > MAX_REPORT_BYTES:
        raise ValueError(f"JUnit report exceeds {MAX_REPORT_BYTES} bytes: {size} bytes")

    root = ElementTree.parse(path, forbid_dtd=True).getroot()
    if root.tag not in _ROOT_TAGS:
        raise ValueError(f"unexpected JUnit root element: {root.tag!r}")

    statuses: dict[str, Status] = {}
    for testcase in root.iter("testcase"):
        test_id = _test_id(testcase)
        status = _status(testcase)
        previous = statuses.get(test_id)
        if previous is None:
            statuses[test_id] = status
            continue
        if not merge_duplicates:
            raise ValueError(f"duplicate test id in JUnit report: {test_id!r}")
        if _STATUS_RANK[status] > _STATUS_RANK[previous]:
            statuses[test_id] = status
    return statuses


def _test_id(testcase: Element) -> str:
    name = _collapse(testcase.get("name", ""))
    for attribute in ("classname", "file"):
        prefix = _collapse(testcase.get(attribute, ""))
        if prefix:
            return f"{prefix}::{name}"
    return name


def _status(testcase: Element) -> Status:
    child_tags = {child.tag for child in testcase}
    for tag, status in _STATUS_PRECEDENCE:
        if tag in child_tags:
            return status
    return "passed"


def _collapse(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip()
