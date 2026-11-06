"""Read the paths that a task's ``test.patch`` creates.

``test.patch`` is hidden material, but a candidate that creates a *new* file at a path the
hidden patch also creates is not editing an existing test: the hidden patch simply supersedes
it. The verifier needs those paths before it applies anything, so this module parses the patch
headers instead of touching a working tree.
"""

from __future__ import annotations

import re

DEV_NULL = "/dev/null"
_DIFF = re.compile(r"^diff --git a/(?P<old>.+) b/(?P<new>.+)$")


def created_paths(patch: bytes) -> frozenset[str]:
    """Paths that ``patch`` creates (``new file mode`` or a ``/dev/null`` source side).

    A section that only modifies a file contributes nothing. Binary sections have no ``+++``
    line, so their symmetric ``diff --git`` header is the fallback for the destination path.
    """
    paths: set[str] = set()
    creates = False
    target: str | None = None

    def close() -> None:
        nonlocal creates, target
        if creates and target is not None:
            paths.add(target)
        creates = False
        target = None

    for line in patch.decode("utf-8", "surrogateescape").split("\n"):
        if line.startswith("diff --git "):
            close()
            header = _DIFF.match(line)
            if header is not None and header["old"] == header["new"]:
                target = header["new"]
        elif line.startswith("new file mode ") or line == "--- " + DEV_NULL:
            creates = True
        elif line.startswith("+++ "):
            target = _clean(line[4:])
    close()
    return frozenset(paths)


def _clean(value: str) -> str:
    """Drop an optional timestamp and the ``b/`` prefix of a ``+++`` header."""
    value = value.split("\t", 1)[0]
    return value.removeprefix("b/")
