"""Read and validate the agent's abort channel from an exported workspace.

``/workspace/.factory/abort.json`` is written by the agent, so both its location
and its contents are untrusted. The path must stay under the exported workspace
and the document must match the ``abort`` object of the output schema.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any

DEFAULT_ABORT_PATH = "/workspace/.factory/abort.json"
WORKSPACE_ROOT = PurePosixPath("/workspace")
MAX_ABORT_BYTES = 64 * 1024
ALLOWED_KEYS = frozenset({"reason", "spec_refs", "test_refs"})


class InvalidAbort(ValueError):
    """The abort file is missing where it should be, or its contents are malformed."""


def read_abort(
    workspace: str | Path, abort_path: str = DEFAULT_ABORT_PATH
) -> dict[str, Any] | None:
    """Return the validated abort document, or ``None`` when the agent did not abort."""
    path = _workspace_path(workspace, abort_path)
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise InvalidAbort(f"abort path is not a regular file: {abort_path}")
    if path.stat().st_size > MAX_ABORT_BYTES:
        raise InvalidAbort(f"abort file is larger than {MAX_ABORT_BYTES} bytes")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InvalidAbort(f"abort file is not valid JSON: {exc}") from exc
    return validate_abort(document)


def validate_abort(document: Any) -> dict[str, Any]:
    """Validate the shape required by ``executor-output.schema.json``."""
    if not isinstance(document, dict):
        raise InvalidAbort("abort document must be a JSON object")
    unknown = set(document) - ALLOWED_KEYS
    if unknown:
        raise InvalidAbort(f"abort document has unknown keys: {sorted(unknown)}")
    reason = document.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise InvalidAbort("abort document needs a non-empty string 'reason'")
    for key in ("spec_refs", "test_refs"):
        refs = document.get(key)
        if key in document and (
            not isinstance(refs, list) or not all(isinstance(item, str) for item in refs)
        ):
            raise InvalidAbort(f"abort document '{key}' must be a list of strings")
    return {key: document[key] for key in ("reason", "spec_refs", "test_refs") if key in document}


def _workspace_path(workspace: str | Path, abort_path: str) -> Path:
    root = Path(workspace).resolve()
    if not root.is_dir():
        raise InvalidAbort(f"workspace is not a directory: {workspace}")
    candidate = PurePosixPath(abort_path)
    if not candidate.is_absolute():
        raise InvalidAbort(f"abort path must be absolute: {abort_path}")
    try:
        relative = candidate.relative_to(WORKSPACE_ROOT)
    except ValueError as exc:
        raise InvalidAbort(f"abort path is outside /workspace: {abort_path}") from exc
    if any(part == ".." for part in relative.parts):
        raise InvalidAbort(f"abort path escapes /workspace: {abort_path}")
    path = root.joinpath(*relative.parts)
    if not path.resolve().is_relative_to(root):
        raise InvalidAbort(f"abort path escapes the exported workspace: {abort_path}")
    return path
