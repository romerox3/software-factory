"""Configuration of the key-minting service.

The JSON file named by ``FACTORY_KEYS_CONFIG`` holds everything but the LiteLLM
master key, which is read only from ``LITELLM_MASTER_KEY``.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONFIG_ENV = "FACTORY_KEYS_CONFIG"
MASTER_KEY_ENV = "LITELLM_MASTER_KEY"

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_TOP_LEVEL_FIELDS = frozenset({"litellm_url", "classes", "tokens"})
_CLASS_FIELDS = frozenset({"team_id", "max_budget_usd", "max_ttl_sec"})
_TOKEN_FIELDS = frozenset({"sha256", "classes"})


class ConfigError(Exception):
    """Raised when the configuration is missing or invalid."""


@dataclass(frozen=True)
class ClassConfig:
    team_id: str
    max_budget_usd: float
    max_ttl_sec: int


@dataclass(frozen=True)
class TokenConfig:
    sha256: str
    classes: tuple[str, ...]


@dataclass(frozen=True)
class KeysConfig:
    litellm_url: str
    classes: Mapping[str, ClassConfig]
    tokens: tuple[TokenConfig, ...]
    master_key: str


def load_config(
    path: str | Path | None = None, environ: Mapping[str, str] | None = None
) -> KeysConfig:
    """Load and validate the configuration, raising ``ConfigError`` on any gap."""
    env = os.environ if environ is None else environ

    master_key = env.get(MASTER_KEY_ENV, "")
    if not master_key:
        raise ConfigError(f"{MASTER_KEY_ENV} is not set")

    config_path = Path(path) if path is not None else Path(env.get(CONFIG_ENV, ""))
    if not str(config_path) or not str(config_path).strip():
        raise ConfigError(f"{CONFIG_ENV} is not set")
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read {CONFIG_ENV} file {config_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{CONFIG_ENV} file {config_path} is not valid JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError("configuration must be a JSON object")
    _reject_unknown(raw, _TOP_LEVEL_FIELDS, "configuration")

    litellm_url = _non_empty_str(raw, "litellm_url")
    classes_raw = _mapping(raw, "classes")
    if not classes_raw:
        raise ConfigError("configuration field 'classes' must not be empty")

    classes: dict[str, ClassConfig] = {}
    for data_class, entry in classes_raw.items():
        _reject_unknown(entry, _CLASS_FIELDS, f"class '{data_class}'")
        team_id = _non_empty_str(entry, "team_id", f"class '{data_class}'")
        max_budget = _number(entry, "max_budget_usd", f"class '{data_class}'")
        max_ttl = _positive_int(entry, "max_ttl_sec", f"class '{data_class}'")
        classes[data_class] = ClassConfig(
            team_id=team_id, max_budget_usd=max_budget, max_ttl_sec=max_ttl
        )

    tokens_raw = raw.get("tokens")
    if not isinstance(tokens_raw, list) or not tokens_raw:
        raise ConfigError("configuration field 'tokens' must be a non-empty list")

    tokens: list[TokenConfig] = []
    for index, entry in enumerate(tokens_raw):
        context = f"token #{index}"
        if not isinstance(entry, dict):
            raise ConfigError(f"{context} must be a JSON object")
        _reject_unknown(entry, _TOKEN_FIELDS, context)
        sha256 = _non_empty_str(entry, "sha256", context)
        if not _SHA256_RE.fullmatch(sha256):
            raise ConfigError(f"{context} field 'sha256' must be 64 lowercase hex characters")
        allowed = entry.get("classes")
        if not isinstance(allowed, list) or not allowed:
            raise ConfigError(f"{context} field 'classes' must be a non-empty list")
        for data_class in allowed:
            if data_class not in classes:
                raise ConfigError(f"{context} lists unknown data_class '{data_class}'")
        tokens.append(TokenConfig(sha256=sha256, classes=tuple(allowed)))

    return KeysConfig(
        litellm_url=litellm_url.rstrip("/"),
        classes=classes,
        tokens=tuple(tokens),
        master_key=master_key,
    )


def _reject_unknown(raw: dict[str, Any], allowed: frozenset[str], context: str) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ConfigError(f"{context} has unknown fields: {', '.join(unknown)}")


def _non_empty_str(raw: dict[str, Any], field: str, context: str = "configuration") -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{context} field '{field}' must be a non-empty string")
    return value


def _mapping(raw: dict[str, Any], field: str) -> dict[str, Any]:
    value = raw.get(field)
    if not isinstance(value, dict):
        raise ConfigError(f"configuration field '{field}' must be a JSON object")
    return value


def _number(raw: dict[str, Any], field: str, context: str) -> float:
    value = raw.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{context} field '{field}' must be a number")
    if value <= 0:
        raise ConfigError(f"{context} field '{field}' must be positive")
    return float(value)


def _positive_int(raw: dict[str, Any], field: str, context: str) -> int:
    value = raw.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{context} field '{field}' must be an integer")
    if value <= 0:
        raise ConfigError(f"{context} field '{field}' must be positive")
    return value
