"""The common base prompt and the hash recorded as ``prompt_sha``."""

from __future__ import annotations

import hashlib
from pathlib import Path

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "base-v1.md"


def sha256_label(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def prompt_text() -> str:
    """The base prompt template, exactly as shipped in ``prompts/base-v1.md``."""
    return PROMPT_PATH.read_text(encoding="utf-8")


def prompt_sha() -> str:
    """Hash of the prompt file the adapter actually uses, not the one the input claims."""
    return sha256_label(PROMPT_PATH.read_bytes())
