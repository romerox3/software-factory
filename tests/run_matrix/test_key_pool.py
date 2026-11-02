"""The pre-minted key pool: hand-out, persistence, spend and exhaustion."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from factory.run_matrix import Deps, KeyPool, KeyPoolExhausted, main

from .support import (
    FIXTURES,
    FakeHarbor,
    FakeVerifier,
    arm,
    write_arms,
    write_manifest,
    write_store,
)


def _sha(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def write_keys(path: Path, keys: list[str], mode: int = 0o600) -> Path:
    path.write_text("\n".join(keys) + "\n", encoding="utf-8")
    path.chmod(mode)
    return path


class FakeGateway:
    def __init__(
        self,
        *,
        spend: float = 0.25,
        logs: list[Mapping[str, Any]] | None = None,
        logs_status: int = 200,
    ) -> None:
        self.spend = spend
        self.logs = logs
        self.logs_status = logs_status
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: Mapping[str, str]) -> tuple[int, Any]:
        self.calls.append((url, dict(headers)))
        if url.endswith("/key/info"):
            return 200, {"info": {"spend": self.spend}}
        if "/spend/logs" in url:
            return self.logs_status, self.logs
        raise AssertionError(f"unexpected URL {url}")


def _pool(tmp_path: Path, keys: list[str], **kwargs: Any) -> KeyPool:
    keys_file = write_keys(tmp_path / "keys.txt", keys)
    kwargs.setdefault("sleep", lambda _seconds: None)
    return KeyPool(
        keys_file,
        tmp_path / "work" / "keys-used.json",
        "http://gateway:4000",
        kwargs.pop("key_budget_usd", 2.0),
        **kwargs,
    )


def test_pool_hands_out_distinct_keys_and_records_only_hashes(tmp_path: Path) -> None:
    pool = _pool(tmp_path, ["sk-one", "sk-two"])

    assert pool.mint("public", 2.0, 60, "run-1") == "sk-one"
    assert pool.mint("public", 2.0, 60, "run-2") == "sk-two"

    used_file = tmp_path / "work" / "keys-used.json"
    document = json.loads(used_file.read_text(encoding="utf-8"))
    assert document == {"run-1": _sha("sk-one"), "run-2": _sha("sk-two")}
    assert "sk-one" not in used_file.read_text(encoding="utf-8")
    assert "sk-two" not in used_file.read_text(encoding="utf-8")


def test_pool_never_reuses_a_recorded_hash_after_a_restart(tmp_path: Path) -> None:
    first = _pool(tmp_path, ["sk-one", "sk-two"])
    assert first.mint("public", 1.0, 60, "run-1") == "sk-one"

    restarted = _pool(tmp_path, ["sk-one", "sk-two"])
    assert restarted.mint("public", 1.0, 60, "run-2") == "sk-two"
    with pytest.raises(KeyPoolExhausted, match="no unused keys"):
        restarted.mint("public", 1.0, 60, "run-3")


def test_pool_refuses_a_loose_keys_file(tmp_path: Path) -> None:
    keys_file = write_keys(tmp_path / "keys.txt", ["sk-one"], mode=0o644)

    with pytest.raises(ValueError, match="600"):
        KeyPool(keys_file, tmp_path / "used.json", "http://gateway:4000")


def test_pool_exhausts_cleanly(tmp_path: Path) -> None:
    pool = _pool(tmp_path, ["sk-one"])

    assert pool.mint("public", 1.0, 60, "run-1") == "sk-one"
    with pytest.raises(KeyPoolExhausted, match="no unused keys"):
        pool.mint("public", 1.0, 60, "run-2")

    document = json.loads((tmp_path / "work" / "keys-used.json").read_text(encoding="utf-8"))
    assert list(document) == ["run-1"]


def test_pool_refuses_an_arm_budget_above_the_key_budget(tmp_path: Path) -> None:
    pool = _pool(tmp_path, ["sk-one"], key_budget_usd=2.0)

    with pytest.raises(ValueError, match="exceeds the key budget"):
        pool.mint("public", 2.01, 60, "run-1")
    assert not (tmp_path / "work" / "keys-used.json").exists()
    assert pool.mint("public", 2.0, 60, "run-1") == "sk-one"


def test_spend_parses_key_info_and_per_request_logs(tmp_path: Path) -> None:
    sleeps: list[float] = []
    logs = [
        {"model": "anthropic/claude-sonnet-5-5", "prompt_tokens": 100, "completion_tokens": 20},
        {"model": "anthropic/claude-sonnet-5-5", "prompt_tokens": 10, "completion_tokens": 2},
    ]
    gateway = FakeGateway(spend=0.42, logs=logs)
    pool = _pool(tmp_path, ["sk-one"], http=gateway, sleep=sleeps.append)

    payload = pool.spend("sk-one")

    assert sleeps == [15.0]
    assert payload["usd_real"] == 0.42
    assert payload["usd_shadow"] == 0.0
    assert payload["requests"] == logs
    assert [url for url, _headers in gateway.calls] == [
        "http://gateway:4000/key/info",
        "http://gateway:4000/spend/logs?api_key=sk-one&summarize=false",
    ]
    for _url, headers in gateway.calls:
        assert headers == {"Authorization": "Bearer sk-one"}


def test_spend_falls_back_when_the_logs_endpoint_fails(tmp_path: Path) -> None:
    gateway = FakeGateway(spend=0.42, logs=[{"prompt_tokens": 100}], logs_status=404)
    pool = _pool(tmp_path, ["sk-one"], http=gateway)

    payload = pool.spend("sk-one")

    assert payload["usd_real"] == 0.42
    assert "requests" not in payload


def _run_args(
    store: Path, arms: Path, manifest: Path, out: Path, work: Path, *extra: str
) -> list[str]:
    return [
        "run",
        "--store",
        str(store),
        "--arms",
        str(arms),
        "--manifest",
        str(manifest),
        "--out",
        str(out),
        "--work",
        str(work),
        "--gateway-url",
        "http://gateway:4000/v1",
        *extra,
    ]


def test_run_uses_the_keys_file_and_stops_when_exhausted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("FACTORY_KEYS_URL", "http://keys.invalid")
    monkeypatch.setenv("FACTORY_KEYS_TOKEN", "token")
    store = write_store(tmp_path)
    arms = write_arms(tmp_path / "arms.json", [arm("A1", k=3)], max_parallel=1)
    manifest = write_manifest(tmp_path / "manifest.json", ["demo-task"])
    keys_file = write_keys(tmp_path / "keys.txt", ["sk-one", "sk-two"])
    gateway = FakeGateway()

    code = main(
        _run_args(
            store,
            arms,
            manifest,
            tmp_path / "out",
            tmp_path / "work",
            "--keys-file",
            str(keys_file),
        ),
        deps=Deps(
            harbor=FakeHarbor(),
            verifier=FakeVerifier(),
            key_http=gateway,
            key_sleep=lambda _seconds: None,
        ),
    )

    assert code == 1
    captured = capsys.readouterr()
    assert "key pool exhausted" in captured.err
    assert "sk-one" not in captured.out + captured.err
    assert "sk-two" not in captured.out + captured.err
    used = json.loads((tmp_path / "work" / "keys-used.json").read_text(encoding="utf-8"))
    assert len(used) == 2
    verdicts = list((tmp_path / "out" / "verdicts").glob("*.json"))
    assert len(verdicts) == 2
    assert len([call for call in gateway.calls if call[0].endswith("/key/info")]) == 2


def test_tokens_come_from_the_agent_stream_when_spend_logs_fail(tmp_path: Path) -> None:
    store = write_store(tmp_path)
    arms = write_arms(
        tmp_path / "arms.json",
        [
            arm(
                "A4",
                executor="opencode",
                gateway_alias="local/nanbeige4.3-33b",
                provider="local",
            )
        ],
        max_parallel=1,
    )
    manifest = write_manifest(tmp_path / "manifest.json", ["demo-task"])
    keys_file = write_keys(tmp_path / "keys.txt", ["sk-one"])
    out = tmp_path / "out"
    gateway = FakeGateway(spend=0.25, logs=None, logs_status=401)

    code = main(
        _run_args(
            store,
            arms,
            manifest,
            out,
            tmp_path / "work",
            "--keys-file",
            str(keys_file),
        ),
        deps=Deps(
            harbor=FakeHarbor(trial_source=FIXTURES / "harbor_opencode"),
            verifier=FakeVerifier(),
            key_http=gateway,
            key_sleep=lambda _seconds: None,
        ),
    )

    assert code == 0
    run_document = json.loads((out / "runs" / "a4-demo-task-r1-a1.json").read_text())
    assert run_document["tokens"] == {
        "input": 150,
        "output": 15,
        "cache_read": 30,
        "cache_write": 3,
        "reasoning": 5,
        "source": "agent",
    }
    assert run_document["cost"]["usd_real"] == 0.0
    assert run_document["cost"]["usd_shadow"] == 0.25
