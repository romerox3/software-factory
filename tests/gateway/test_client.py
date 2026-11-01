"""The orchestrator client speaks the service contract."""

from __future__ import annotations

import json

import httpx
import respx

from factory.gateway.client import FactoryKeysClient

from .test_support import EMITTED_KEY, KEYS_URL

MINT_URL = f"{KEYS_URL}/mint"
SPEND_URL = f"{KEYS_URL}/spend"
REVOKE_URL = f"{KEYS_URL}/revoke"


@respx.mock
def test_mint_spend_and_revoke() -> None:
    mint = respx.post(MINT_URL).mock(
        return_value=httpx.Response(200, json={"key": EMITTED_KEY, "expires_in_sec": 60})
    )
    spend = respx.post(SPEND_URL).mock(
        return_value=httpx.Response(200, json={"spend_usd": 0.5, "requests": []})
    )
    revoke = respx.post(REVOKE_URL).mock(return_value=httpx.Response(200, json={}))

    with FactoryKeysClient(KEYS_URL, "orchestrator-token") as client:
        key = client.mint("public", 0.5, 60, "run-7")
        payload = client.spend(key)
        client.revoke(key)

    assert key == EMITTED_KEY
    assert payload == {"spend_usd": 0.5, "requests": []}
    assert json.loads(mint.calls.last.request.content) == {
        "data_class": "public",
        "budget_usd": 0.5,
        "ttl_sec": 60,
        "run_id": "run-7",
    }
    assert json.loads(spend.calls.last.request.content) == {"key": EMITTED_KEY}
    assert json.loads(revoke.calls.last.request.content) == {"key": EMITTED_KEY}
    assert mint.calls.last.request.headers["authorization"] == "Bearer orchestrator-token"
