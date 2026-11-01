"""Where a task's repository lives inside its image (``repo.workdir``).

Real SWE-bench-style images keep the checkout in something other than
``/workspace`` (``/testbed`` is the usual one), so every consumer has to read the
path from the task instead of assuming a directory. The default keeps the toy
fixtures and everything written before this field existed working.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DEFAULT_WORKDIR = "/workspace"


def workdir_of(task: Mapping[str, Any]) -> str:
    """Return ``repo.workdir`` of a task document, or the default."""
    repo = task.get("repo")
    if not isinstance(repo, Mapping):
        return DEFAULT_WORKDIR
    workdir = repo.get("workdir")
    return workdir if isinstance(workdir, str) and workdir else DEFAULT_WORKDIR
