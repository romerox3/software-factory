"""The key service mints, inspects and revokes keys without leaking secrets."""

from __future__ import annotations

import json
import logging
import math

import httpx
import pytest
import respx

from factory.gateway.config import ConfigError
from factory.gateway.service import bind_address

from .test_support import (
    EMITTED_KEY,
    LITELLM_URL,
    MASTER_KEY,
    ORCHESTRATOR_TOKEN,
    VALID_MINT,
    VERIFIER_TOKEN,
    bearer,
    make_client,
)

GENERATE_URL = f"{LITELLM_URL}/key/generate"
DELETE_URL = f"{LITELLM_URL}/key/delete"
SPEND_URL = f"{LITELLM_URL}/spend/logs"


def mock_generate() -> respx.Route:
    return respx.post(GENERATE_URL).mock(
        return_value=httpx.Response(200, json={"key": EMITTED_KEY})
    )


def test_bind_address_defaults_to_loopback() -> None:
    assert bind_address({}) == ("127.0.0.1", 8000)


def test_bind_address_reads_host_and_port_from_env() -> None:
    env = {"FACTORY_KEYS_HOST": "127.0.0.2", "FACTORY_KEYS_PORT": "9000"}

    assert bind_address(env) == ("127.0.0.2", 9000)


@pytest.mark.parametrize("host", ["0.0.0.0", "::"])
def test_all_interfaces_refused_without_the_override(host, caplog) -> None:
    with pytest.raises(ConfigError, match="FACTORY_KEYS_ALLOW_ALL_INTERFACES"):
        bind_address({"FACTORY_KEYS_HOST": host})

    assert not caplog.records


@pytest.mark.parametrize("host", ["0.0.0.0", "::"])
def test_all_interfaces_allowed_with_a_logged_warning(host, caplog) -> None:
    caplog.set_level(logging.WARNING)

    assert bind_address({"FACTORY_KEYS_HOST": host, "FACTORY_KEYS_ALLOW_ALL_INTERFACES": "1"}) == (
        host,
        8000,
    )
    assert "every interface" in caplog.text


def test_all_interfaces_override_must_be_exactly_one() -> None:
    for value in ("true", "yes", "0", ""):
        with pytest.raises(ConfigError, match="FACTORY_KEYS_ALLOW_ALL_INTERFACES"):
            bind_address(
                {"FACTORY_KEYS_HOST": "0.0.0.0", "FACTORY_KEYS_ALLOW_ALL_INTERFACES": value}
            )


@pytest.mark.parametrize("port", ["http", "0", "65536", "-1"])
def test_invalid_port_fails_to_start(port) -> None:
    with pytest.raises(ConfigError, match="FACTORY_KEYS_PORT"):
        bind_address({"FACTORY_KEYS_PORT": port})


@respx.mock
def test_mint_uses_class_team_budget_and_duration(tmp_path) -> None:
    generate = mock_generate()
    client = make_client(tmp_path)

    response = client.post("/mint", json=VALID_MINT, headers=bearer(ORCHESTRATOR_TOKEN))

    assert response.status_code == 200
    assert response.json() == {"key": EMITTED_KEY, "expires_in_sec": 120}
    assert generate.call_count == 1
    request = generate.calls.last.request
    sent = json.loads(request.content)
    assert sent["team_id"] == "team-public"
    assert sent["max_budget"] == 0.25
    assert sent["duration"] == "120s"
    assert sent["metadata"]["run_id"] == "run-1"
    assert request.headers["authorization"] == f"Bearer {MASTER_KEY}"


@pytest.mark.parametrize(
    ("headers", "body", "expected_status"),
    [
        ({}, VALID_MINT, 401),
        (bearer("unknown-token"), VALID_MINT, 401),
        (bearer(ORCHESTRATOR_TOKEN), {**VALID_MINT, "data_class": "verifier"}, 403),
        (bearer(ORCHESTRATOR_TOKEN), {**VALID_MINT, "data_class": "nope"}, 400),
        (bearer(ORCHESTRATOR_TOKEN), {**VALID_MINT, "budget_usd": 0}, 400),
        (bearer(ORCHESTRATOR_TOKEN), {**VALID_MINT, "budget_usd": -1}, 400),
        (
            bearer(ORCHESTRATOR_TOKEN),
            {key: value for key, value in VALID_MINT.items() if key != "budget_usd"},
            400,
        ),
        (bearer(ORCHESTRATOR_TOKEN), {**VALID_MINT, "budget_usd": 1.01}, 400),
        (bearer(ORCHESTRATOR_TOKEN), {**VALID_MINT, "ttl_sec": 0}, 400),
        (bearer(ORCHESTRATOR_TOKEN), {**VALID_MINT, "ttl_sec": 3601}, 400),
    ],
)
@respx.mock
def test_mint_rejections_never_reach_litellm(tmp_path, headers, body, expected_status) -> None:
    generate = mock_generate()
    client = make_client(tmp_path)

    response = client.post("/mint", json=body, headers=headers)

    assert response.status_code == expected_status
    assert not generate.called


@respx.mock
def test_mint_rejects_a_non_finite_budget(tmp_path) -> None:
    generate = mock_generate()
    client = make_client(tmp_path)
    body = json.dumps({**VALID_MINT, "budget_usd": math.nan}).encode("utf-8")

    response = client.post(
        "/mint",
        content=body,
        headers={**bearer(ORCHESTRATOR_TOKEN), "content-type": "application/json"},
    )

    assert response.status_code == 400
    assert not generate.called


@respx.mock
def test_foreign_token_cannot_revoke_or_read_spend(tmp_path) -> None:
    mock_generate()
    delete = respx.post(DELETE_URL).mock(return_value=httpx.Response(200, json={}))
    spend = respx.get(SPEND_URL).mock(return_value=httpx.Response(200, json=[]))
    client = make_client(tmp_path)

    minted = client.post("/mint", json=VALID_MINT, headers=bearer(ORCHESTRATOR_TOKEN))
    key = minted.json()["key"]

    revoked = client.post("/revoke", json={"key": key}, headers=bearer(VERIFIER_TOKEN))
    inspected = client.post("/spend", json={"key": key}, headers=bearer(VERIFIER_TOKEN))
    unknown = client.post(
        "/revoke", json={"key": "sk-never-minted"}, headers=bearer(ORCHESTRATOR_TOKEN)
    )

    assert minted.status_code == 200
    assert revoked.status_code == 404
    assert inspected.status_code == 404
    assert unknown.status_code == 404
    assert not delete.called
    assert not spend.called


@respx.mock
def test_spend_aggregates_logs_of_own_key(tmp_path) -> None:
    mock_generate()
    respx.get(SPEND_URL).mock(
        return_value=httpx.Response(
            200,
            json=[
                {"model": "gpt-a", "prompt_tokens": 10, "completion_tokens": 5, "spend": 0.25},
                {"model": "gpt-a", "prompt_tokens": 2, "completion_tokens": 1, "spend": 0.125},
            ],
        )
    )
    client = make_client(tmp_path)
    key = client.post("/mint", json=VALID_MINT, headers=bearer(ORCHESTRATOR_TOKEN)).json()["key"]

    response = client.post("/spend", json={"key": key}, headers=bearer(ORCHESTRATOR_TOKEN))

    assert response.status_code == 200
    assert response.json() == {
        "spend_usd": pytest.approx(0.375),
        "requests": [
            {"model": "gpt-a", "prompt_tokens": 10, "completion_tokens": 5, "spend": 0.25},
            {"model": "gpt-a", "prompt_tokens": 2, "completion_tokens": 1, "spend": 0.125},
        ],
    }


@respx.mock
def test_master_key_and_minted_key_never_leak_outside_mint_body(tmp_path, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    mock_generate()
    respx.get(SPEND_URL).mock(
        return_value=httpx.Response(
            200, json=[{"model": "gpt-a", "prompt_tokens": 1, "completion_tokens": 1, "spend": 0.1}]
        )
    )
    respx.post(DELETE_URL).mock(return_value=httpx.Response(200, json={}))
    client = make_client(tmp_path)

    minted = client.post("/mint", json=VALID_MINT, headers=bearer(ORCHESTRATOR_TOKEN))
    assert minted.json()["key"] == EMITTED_KEY
    spend = client.post("/spend", json={"key": EMITTED_KEY}, headers=bearer(ORCHESTRATOR_TOKEN))
    revoke = client.post("/revoke", json={"key": EMITTED_KEY}, headers=bearer(ORCHESTRATOR_TOKEN))
    foreign = client.post("/revoke", json={"key": EMITTED_KEY}, headers=bearer(VERIFIER_TOKEN))

    assert MASTER_KEY not in caplog.text
    assert EMITTED_KEY not in caplog.text
    for response in (spend, revoke, foreign):
        assert MASTER_KEY not in response.text
        assert EMITTED_KEY not in response.text
