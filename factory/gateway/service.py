"""Starlette service that mints, inspects and revokes LiteLLM virtual keys."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import os
import threading
from collections.abc import Mapping
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from factory.gateway.config import ConfigError, KeysConfig, TokenConfig, load_config
from factory.gateway.litellm_admin import LiteLLMAdmin, LiteLLMError

HOST_ENV = "FACTORY_KEYS_HOST"
PORT_ENV = "FACTORY_KEYS_PORT"
ALLOW_ALL_INTERFACES_ENV = "FACTORY_KEYS_ALLOW_ALL_INTERFACES"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
ALL_INTERFACES = frozenset({"0.0.0.0", "::"})

_log = logging.getLogger(__name__)


class KeyBook:
    """Keys minted by this service, with the token that requested them."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._owners: dict[str, tuple[str, str]] = {}

    def add(self, key: str, token_sha256: str, data_class: str) -> None:
        with self._lock:
            self._owners[key] = (token_sha256, data_class)

    def owner(self, key: str) -> tuple[str, str] | None:
        with self._lock:
            return self._owners.get(key)

    def discard(self, key: str) -> None:
        with self._lock:
            self._owners.pop(key, None)


def create_app(config: KeysConfig) -> Starlette:
    admin = LiteLLMAdmin(config.litellm_url, config.master_key)
    book = KeyBook()

    async def mint(request: Request) -> Response:
        token = _authenticate(config, request)
        if token is None:
            return _error(401, "missing or unknown token")

        body = await _json_object(request)
        if body is None:
            return _error(400, "body must be a JSON object")

        data_class = body.get("data_class")
        if not isinstance(data_class, str) or data_class not in config.classes:
            return _error(400, "unknown data_class")
        if data_class not in token.classes:
            return _error(403, "data_class not allowed for this token")

        budget = body.get("budget_usd")
        if isinstance(budget, bool) or not isinstance(budget, (int, float)):
            return _error(400, "budget_usd must be a number")
        budget = float(budget)
        if not math.isfinite(budget) or budget <= 0:
            return _error(400, "budget_usd must be positive")
        class_config = config.classes[data_class]
        if budget > class_config.max_budget_usd:
            return _error(400, "budget_usd exceeds the class maximum")

        ttl = body.get("ttl_sec")
        if isinstance(ttl, bool) or not isinstance(ttl, int):
            return _error(400, "ttl_sec must be an integer")
        if ttl <= 0 or ttl > class_config.max_ttl_sec:
            return _error(400, "ttl_sec is outside the class range")

        run_id = body.get("run_id")
        if not isinstance(run_id, str) or not run_id.strip():
            return _error(400, "run_id must be a non-empty string")

        try:
            key = admin.generate_key(
                team_id=class_config.team_id,
                max_budget=budget,
                duration_sec=ttl,
                metadata={"run_id": run_id, "data_class": data_class},
            )
        except LiteLLMError:
            return _error(502, "gateway error")

        book.add(key, token.sha256, data_class)
        return JSONResponse({"key": key, "expires_in_sec": ttl})

    async def revoke(request: Request) -> Response:
        token = _authenticate(config, request)
        if token is None:
            return _error(401, "missing or unknown token")

        key = await _key_from_body(request)
        if key is None:
            return _error(400, "body must carry a key")
        owner = book.owner(key)
        if owner is None or owner[0] != token.sha256:
            return _error(404, "key not minted by this token")

        try:
            admin.delete_key(key)
        except LiteLLMError:
            return _error(502, "gateway error")
        book.discard(key)
        return JSONResponse({})

    async def spend(request: Request) -> Response:
        token = _authenticate(config, request)
        if token is None:
            return _error(401, "missing or unknown token")

        key = await _key_from_body(request)
        if key is None:
            return _error(400, "body must carry a key")
        owner = book.owner(key)
        if owner is None or owner[0] != token.sha256:
            return _error(404, "key not minted by this token")

        try:
            logs = admin.spend_logs(key)
        except LiteLLMError:
            return _error(502, "gateway error")

        return JSONResponse(
            {
                "spend_usd": sum(_as_float(entry.get("spend")) for entry in logs),
                "requests": [
                    {
                        "model": entry.get("model"),
                        "prompt_tokens": _as_int(entry.get("prompt_tokens")),
                        "completion_tokens": _as_int(entry.get("completion_tokens")),
                        "spend": _as_float(entry.get("spend")),
                    }
                    for entry in logs
                ],
            }
        )

    return Starlette(
        routes=[
            Route("/mint", mint, methods=["POST"]),
            Route("/revoke", revoke, methods=["POST"]),
            Route("/spend", spend, methods=["POST"]),
        ]
    )


def _authenticate(config: KeysConfig, request: Request) -> TokenConfig | None:
    scheme, _, credentials = request.headers.get("authorization", "").partition(" ")
    token = credentials.strip()
    if scheme.lower() != "bearer" or not token:
        return None
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    for candidate in config.tokens:
        if hmac.compare_digest(digest, candidate.sha256):
            return candidate
    return None


async def _json_object(request: Request) -> dict[str, Any] | None:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return None
    return body if isinstance(body, dict) else None


async def _key_from_body(request: Request) -> str | None:
    body = await _json_object(request)
    if body is None:
        return None
    key = body.get("key")
    return key if isinstance(key, str) and key else None


def _as_float(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value) if math.isfinite(value) else 0.0


def _as_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


def _error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


def bind_address(env: Mapping[str, str]) -> tuple[str, int]:
    """Host and port to listen on, refusing to expose every interface by default."""
    host = env.get(HOST_ENV, "").strip() or DEFAULT_HOST
    port_raw = env.get(PORT_ENV, "").strip() or str(DEFAULT_PORT)
    try:
        port = int(port_raw)
    except ValueError:
        raise ConfigError(f"{PORT_ENV} must be an integer, got {port_raw!r}") from None
    if not 1 <= port <= 65535:
        raise ConfigError(f"{PORT_ENV} must be between 1 and 65535, got {port}")

    if host in ALL_INTERFACES:
        if env.get(ALLOW_ALL_INTERFACES_ENV) != "1":
            raise ConfigError(
                f"{HOST_ENV}={host} exposes the service on every interface; "
                f"set {ALLOW_ALL_INTERFACES_ENV}=1 to allow it"
            )
        _log.warning(
            "%s=%s exposes the service on every interface; allowed by %s=1",
            HOST_ENV,
            host,
            ALLOW_ALL_INTERFACES_ENV,
        )
    return host, port


def main() -> int:
    import uvicorn

    host, port = bind_address(os.environ)
    app = create_app(load_config())
    uvicorn.run(app, host=host, port=port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
