"""Shared helpers for the gateway tests (no tests live here)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from starlette.testclient import TestClient

from factory.gateway.config import KeysConfig, load_config
from factory.gateway.service import create_app

LITELLM_URL = "http://litellm.test:4000"
KEYS_URL = "http://keys.test:8080"
MASTER_KEY = "sk-master-example-do-not-leak"
EMITTED_KEY = "sk-emitted-example-do-not-leak"
ORCHESTRATOR_TOKEN = "orchestrator-token"
VERIFIER_TOKEN = "verifier-token"

VALID_MINT = {
    "data_class": "public",
    "budget_usd": 0.25,
    "ttl_sec": 120,
    "run_id": "run-1",
}


def token_sha256(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def base_config() -> dict[str, Any]:
    return {
        "litellm_url": LITELLM_URL,
        "classes": {
            "public": {"team_id": "team-public", "max_budget_usd": 1.0, "max_ttl_sec": 3600},
            "verifier": {"team_id": "team-verifier", "max_budget_usd": 5.0, "max_ttl_sec": 7200},
        },
        "tokens": [
            {"sha256": token_sha256(ORCHESTRATOR_TOKEN), "classes": ["public"]},
            {"sha256": token_sha256(VERIFIER_TOKEN), "classes": ["verifier"]},
        ],
    }


def write_config(tmp_path: Path, config: dict[str, Any] | None = None) -> Path:
    path = tmp_path / "keys.json"
    path.write_text(json.dumps(base_config() if config is None else config), encoding="utf-8")
    return path


def load_test_config(tmp_path: Path, config: dict[str, Any] | None = None) -> KeysConfig:
    return load_config(write_config(tmp_path, config), environ={"LITELLM_MASTER_KEY": MASTER_KEY})


def make_client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(load_test_config(tmp_path)))


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
