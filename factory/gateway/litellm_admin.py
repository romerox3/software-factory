"""Minimal LiteLLM admin client: keys and spend logs.

Only the key-minting service holds the master key; error messages never include
it (nor the key being operated on).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

TIMEOUT_SEC = 30.0

# httpx logs full request URLs at INFO; /spend/logs carries the key as a query
# parameter, so this logger must stay quiet to keep keys out of logs.
logging.getLogger("httpx").setLevel(logging.WARNING)


class LiteLLMError(Exception):
    """A LiteLLM admin call failed. The message never carries credentials."""

    def __init__(self, status_code: int, method: str, path: str) -> None:
        self.status_code = status_code
        self.method = method
        self.path = path
        super().__init__(f"LiteLLM {method} {path} failed with HTTP {status_code}")


class LiteLLMAdmin:
    def __init__(self, base_url: str, master_key: str) -> None:
        self._base_url = base_url
        self._master_key = master_key

    def generate_key(
        self,
        team_id: str,
        max_budget: float,
        duration_sec: int,
        metadata: dict[str, Any],
    ) -> str:
        payload = {
            "team_id": team_id,
            "max_budget": max_budget,
            "duration": f"{duration_sec}s",
            "metadata": metadata,
        }
        data = self._request("POST", "/key/generate", json=payload)
        key = data.get("key") if isinstance(data, dict) else None
        if not isinstance(key, str) or not key:
            raise LiteLLMError(0, "POST", "/key/generate")
        return key

    def key_info(self, key: str) -> dict[str, Any]:
        data = self._request("GET", "/key/info", params={"key": key})
        if not isinstance(data, dict):
            raise LiteLLMError(0, "GET", "/key/info")
        return data

    def delete_key(self, key: str) -> None:
        self._request("POST", "/key/delete", json={"keys": [key]})

    def spend_logs(self, key: str) -> list[dict[str, Any]]:
        data = self._request("GET", "/spend/logs", params={"api_key": key})
        if not isinstance(data, list):
            raise LiteLLMError(0, "GET", "/spend/logs")
        return data

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = {"Authorization": f"Bearer {self._master_key}"}
        with httpx.Client(base_url=self._base_url, timeout=TIMEOUT_SEC, headers=headers) as http:
            response = http.request(method, path, **kwargs)
        if response.status_code >= 400:
            raise LiteLLMError(response.status_code, method, path)
        return response.json()
