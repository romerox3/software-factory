"""End-to-end smoke check of the gateway: mint, model policy, spend, revoke.

Run with ``python -m factory.gateway.smoke`` and the environment described in
``REQUIRED_ENV``. It never prints the virtual keys.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from factory.gateway.client import FactoryKeysClient

REQUIRED_ENV = (
    "FACTORY_KEYS_URL",
    "FACTORY_KEYS_TOKEN",
    "FACTORY_GATEWAY_URL",
    "FACTORY_SMOKE_PLAN",
)

MINT_BUDGET_USD = 0.05
MINT_TTL_SEC = 600
SPEND_TIMEOUT_SEC = 20.0
SPEND_POLL_SEC = 1.0
CHAT_TIMEOUT_SEC = 120.0


@dataclass
class Row:
    data_class: str
    allowed_model: str
    allowed_status: int | None
    denied_model: str
    denied_status: int | None
    spend_usd: float
    tokens: int
    ok: bool
    note: str


def main(environ: Mapping[str, str] | None = None) -> int:
    env = os.environ if environ is None else environ

    missing = [name for name in REQUIRED_ENV if not env.get(name)]
    if missing:
        raise SystemExit("missing required environment variable(s): " + ", ".join(missing))

    plan = _parse_plan(env["FACTORY_SMOKE_PLAN"])

    rows: list[Row] = []
    with FactoryKeysClient(env["FACTORY_KEYS_URL"], env["FACTORY_KEYS_TOKEN"]) as keys:
        for data_class, (allowed_model, denied_model) in plan.items():
            rows.append(
                _probe_class(
                    keys,
                    env["FACTORY_GATEWAY_URL"],
                    data_class,
                    allowed_model,
                    denied_model,
                )
            )

    _print_table(rows)
    return 0 if all(row.ok for row in rows) else 1


def _parse_plan(raw: str) -> dict[str, tuple[str, str]]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"FACTORY_SMOKE_PLAN is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict) or not parsed:
        raise SystemExit("FACTORY_SMOKE_PLAN must be a non-empty JSON object")

    plan: dict[str, tuple[str, str]] = {}
    for data_class, entry in parsed.items():
        if not isinstance(entry, dict):
            raise SystemExit(f"FACTORY_SMOKE_PLAN entry '{data_class}' must be a JSON object")
        allowed = entry.get("allowed")
        denied = entry.get("denied")
        if not isinstance(allowed, str) or not allowed or not isinstance(denied, str) or not denied:
            raise SystemExit(
                f"FACTORY_SMOKE_PLAN entry '{data_class}' needs string 'allowed' and 'denied'"
            )
        plan[data_class] = (allowed, denied)
    return plan


def _probe_class(
    keys: FactoryKeysClient,
    gateway_url: str,
    data_class: str,
    allowed_model: str,
    denied_model: str,
) -> Row:
    run_id = f"smoke-{data_class}-{uuid.uuid4().hex[:8]}"
    allowed_status: int | None = None
    denied_status: int | None = None
    spend_usd = 0.0
    tokens = 0
    notes: list[str] = []

    key = keys.mint(data_class, MINT_BUDGET_USD, MINT_TTL_SEC, run_id)
    try:
        allowed_status = _chat(gateway_url, key, allowed_model)
        if allowed_status != 200:
            notes.append(f"allowed model answered {allowed_status}")

        denied_status = _chat(gateway_url, key, denied_model)
        if denied_status not in (401, 403):
            notes.append(f"denied model answered {denied_status}")

        deadline = time.monotonic() + SPEND_TIMEOUT_SEC
        while True:
            spend_usd, tokens = _spend_totals(keys.spend(key))
            if tokens > 0 or time.monotonic() >= deadline:
                break
            time.sleep(SPEND_POLL_SEC)
        if tokens <= 0:
            notes.append(f"no tokens in spend after {int(SPEND_TIMEOUT_SEC)}s")
    except httpx.HTTPError as exc:
        notes.append(f"{type(exc).__name__}: {exc}")
    finally:
        try:
            keys.revoke(key)
        except httpx.HTTPError as exc:
            notes.append(f"revoke failed: {type(exc).__name__}")

    ok = allowed_status == 200 and denied_status in (401, 403) and tokens > 0 and not notes
    return Row(
        data_class=data_class,
        allowed_model=allowed_model,
        allowed_status=allowed_status,
        denied_model=denied_model,
        denied_status=denied_status,
        spend_usd=spend_usd,
        tokens=tokens,
        ok=ok,
        note="; ".join(notes),
    )


def _chat(gateway_url: str, key: str, model: str) -> int:
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with OK."}],
        "max_tokens": 8,
    }
    with httpx.Client(
        base_url=gateway_url.rstrip("/"),
        headers={"Authorization": f"Bearer {key}"},
        timeout=CHAT_TIMEOUT_SEC,
    ) as http:
        return http.post("/v1/chat/completions", json=body).status_code


def _spend_totals(payload: dict[str, Any]) -> tuple[float, int]:
    spend_usd = float(payload.get("spend_usd") or 0.0)
    tokens = 0
    for entry in payload.get("requests") or []:
        tokens += int(entry.get("prompt_tokens") or 0)
        tokens += int(entry.get("completion_tokens") or 0)
    return spend_usd, tokens


def _print_table(rows: list[Row]) -> None:
    headers = ("data_class", "allowed", "status", "denied", "status", "spend_usd", "tokens", "ok")
    body = [
        (
            row.data_class,
            row.allowed_model,
            str(row.allowed_status),
            row.denied_model,
            str(row.denied_status),
            f"{row.spend_usd:.6f}",
            str(row.tokens),
            "yes" if row.ok else f"NO ({row.note})",
        )
        for row in rows
    ]
    widths = [max(len(str(cell)) for cell in column) for column in zip(headers, *body)]
    line = "  ".join(str(cell).ljust(width) for cell, width in zip(headers, widths))
    print(line)
    print("  ".join("-" * width for width in widths))
    for row in body:
        print("  ".join(str(cell).ljust(width) for cell, width in zip(row, widths)))


if __name__ == "__main__":
    raise SystemExit(main())
