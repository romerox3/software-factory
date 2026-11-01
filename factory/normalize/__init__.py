"""Turn raw executor output into ``trajectory-event`` objects.

The format is always explicit: there is no sniffing. Each parser lives in its
own module and shares the state and helpers in :mod:`factory.normalize.core`.
"""

from __future__ import annotations

from collections.abc import Callable

from .claude_code import normalize as _normalize_claude_code
from .codex import normalize as _normalize_codex
from .core import Event, Normalizer, Trajectory, canonical_tool
from .mini_swe_agent import normalize as _normalize_mini_swe_agent
from .opencode import normalize as _normalize_opencode

Parser = Callable[[Normalizer, str], None]

FORMATS: dict[str, Parser] = {
    "claude-code": _normalize_claude_code,
    "codex": _normalize_codex,
    "opencode": _normalize_opencode,
    "mini-swe-agent": _normalize_mini_swe_agent,
}


def normalize_text(fmt: str, run_id: str, text: str) -> Trajectory:
    """Normalize ``text`` produced by the executor format ``fmt``."""
    try:
        parser = FORMATS[fmt]
    except KeyError:
        raise ValueError(f"unknown format: {fmt!r}") from None
    normalizer = Normalizer(run_id)
    parser(normalizer, text)
    return Trajectory(
        run_id=run_id,
        format=fmt,
        events=normalizer.events,
        unmapped=normalizer.unmapped,
        skipped_non_json=normalizer.skipped_non_json,
    )


__all__ = ["FORMATS", "Event", "Normalizer", "Trajectory", "canonical_tool", "normalize_text"]
