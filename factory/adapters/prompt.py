"""The common base prompt and the hash recorded as ``prompt_sha``."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "base-v1.md"
PLACEHOLDER_RE = re.compile(r"\{\{\s*(.*?)\s*\}\}")


def sha256_label(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def prompt_text() -> str:
    """The base prompt template, exactly as shipped in ``prompts/base-v1.md``."""
    return PROMPT_PATH.read_text(encoding="utf-8")


def render_prompt(task: str, workdir: str) -> str:
    """Fill the base prompt template for one task and its repository directory."""
    values = {"task": task, "workdir": workdir}

    def substitute(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise ValueError(f"unknown prompt placeholder: {{{{ {key} }}}}")
        return values[key]

    return PLACEHOLDER_RE.sub(substitute, prompt_text())


def prompt_sha() -> str:
    """Hash of the prompt file the adapter actually uses, not the one the input claims."""
    return sha256_label(PROMPT_PATH.read_bytes())
