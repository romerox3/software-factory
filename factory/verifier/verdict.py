"""The verdict document, its feedback whitelist and its validation."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema

VERIFIER_VERSION = "0.1.0"
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "verdict.schema.json"
HIDDEN_CHECKS_MESSAGE = "fallan comprobaciones ocultas"

ACCEPT = "accept"
REJECT = "reject"
CHEAT = "cheat_suspected"
ERROR_INFRA = "error_infra"


def sha256_label(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def feedback_patch_invalid() -> dict[str, Any]:
    return {"type": "patch_invalid"}


def feedback_diff_guard(rule_ids: list[str]) -> dict[str, Any]:
    return {"type": "diff_guard", "rule_ids": sorted(rule_ids)}


def feedback_visible_test(test_id: str, status: str) -> dict[str, Any]:
    return {"type": "visible_test", "id": test_id, "status": status}


def feedback_hidden() -> dict[str, Any]:
    return {"type": "hidden_checks", "message": HIDDEN_CHECKS_MESSAGE}


@dataclass
class Verdict:
    """What the verifier decided about one diff. ``feedback`` is the only generator-facing part."""

    run_id: str
    task_id: str
    arm: str
    attempt: int
    repetition: int
    verdict: str
    reason: str
    diff_sha: str
    verify_cost_usd: float = 0.0
    category: str | None = None
    rule_ids: list[str] = field(default_factory=list)
    feedback_items: list[dict[str, Any]] = field(default_factory=list)
    hashes: dict[str, str | None] = field(default_factory=dict)
    isolated: bool | None = None
    canary: bool | None = None
    hard: dict[str, Any] | None = None
    diagnostics: dict[str, Any] | None = None
    informative: dict[str, Any] | None = None
    duration_s: float = 0.0

    @property
    def feedback(self) -> dict[str, Any] | None:
        return {"items": self.feedback_items} if self.feedback_items else None

    def to_dict(self) -> dict[str, Any]:
        document: dict[str, Any] = {
            "schema_version": "1",
            "run_id": self.run_id,
            "task_id": self.task_id,
            "arm": self.arm,
            "attempt": self.attempt,
            "repetition": self.repetition,
            "verdict": self.verdict,
            "reason": self.reason,
            "verify_cost_usd": self.verify_cost_usd,
            "diff_sha": self.diff_sha,
            "verifier_version": VERIFIER_VERSION,
            "duration_s": round(self.duration_s, 3),
            "feedback": self.feedback,
        }
        optional: dict[str, Any] = {
            "category": self.category,
            "rule_ids": self.rule_ids or None,
            "hashes": self.hashes or None,
            "isolated": self.isolated,
            "canary": self.canary,
            "hard": self.hard,
            "diagnostics": self.diagnostics,
            "informative": self.informative,
        }
        document.update({key: value for key, value in optional.items() if value is not None})
        return document


def validate_document(document: dict[str, Any]) -> None:
    """Raise ``jsonschema.ValidationError`` when ``document`` breaks the verdict schema."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(document)


def write_verdict(verdict: Verdict, out_dir: Path) -> Path:
    """Validate and atomically write ``verdict.json`` in ``out_dir`` (the verifier's store)."""
    document = verdict.to_dict()
    validate_document(document)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "verdict.json"
    fd, tmp_name = tempfile.mkstemp(dir=out_dir, prefix=".verdict.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_name, target)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return target
