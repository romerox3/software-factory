"""Client of the key-minting service, used by the orchestrator."""

from __future__ import annotations

from typing import Any, Self

import httpx

DEFAULT_TIMEOUT_SEC = 30.0


class FactoryKeysClient:
    def __init__(self, base_url: str, token: str, timeout: float = DEFAULT_TIMEOUT_SEC) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )

    def mint(self, data_class: str, budget_usd: float, ttl_sec: int, run_id: str) -> str:
        response = self._client.post(
            "/mint",
            json={
                "data_class": data_class,
                "budget_usd": budget_usd,
                "ttl_sec": ttl_sec,
                "run_id": run_id,
            },
        )
        response.raise_for_status()
        return response.json()["key"]

    def spend(self, key: str) -> dict[str, Any]:
        response = self._client.post("/spend", json={"key": key})
        response.raise_for_status()
        return response.json()

    def revoke(self, key: str) -> None:
        response = self._client.post("/revoke", json={"key": key})
        response.raise_for_status()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
