"""Support fakes for the matrix runner tests (no Docker, no network)."""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from factory.adapters.diff import empty_diff
from factory.adapters.exit import ExitDecision
from factory.adapters.output import RunTiming, build_run_document, write_run_document
from factory.verifier.verdict import Verdict, sha256_label, write_verdict

DIGEST = "sha256:" + "a" * 64
KEY = "sk-test-DEADBEEF"
TASK_ID = "demo-task"
FIXTURES = Path(__file__).parent / "fixtures"
HARBOR_TRIAL = FIXTURES / "harbor_trial"


def write_store(root: Path, task_ids: Sequence[str] = (TASK_ID,)) -> Path:
    """A minimal verifier/task store: visible task + valid revalidation."""
    store = root / "store"
    for task_id in task_ids:
        visible = store / "visible" / task_id
        (visible / "openspec" / "changes" / task_id).mkdir(parents=True)
        (visible / "openspec" / "changes" / task_id / "proposal.md").write_text(
            f"# {task_id}\n\nFix it.\n", encoding="utf-8"
        )
        (visible / "tests").mkdir()
        (visible / "tests" / "test_demo.py").write_text(
            "def test_demo():\n    assert True\n", encoding="utf-8"
        )
        (visible / "factory.task.json").write_text(
            json.dumps(
                {
                    "schema_version": "1",
                    "task_id": task_id,
                    "class": "C1",
                    "data_class": "public",
                    "repo": {"commit": "0" * 40},
                    "image": "python@sha256:" + "0" * 64,
                    "visible_tests": {
                        "command": "python -m pytest -q tests",
                        "ids": ["tests/test_demo.py::test_demo"],
                    },
                    "budget": {"usd": 1.0, "max_turns": 20, "timeout_sec": 300},
                }
            ),
            encoding="utf-8",
        )
        hidden = store / "hidden" / task_id
        hidden.mkdir(parents=True)
        (hidden / "revalidation.json").write_text(json.dumps({"valid": True}), encoding="utf-8")
        (hidden / "verifier.json").write_text(json.dumps({"framework": "pytest"}), encoding="utf-8")
    return store


def add_git_snapshot(store: Path, task_id: str = TASK_ID) -> str:
    """Give a visible task a real fresh-init snapshot and return its HEAD."""
    snapshot = store / "visible" / task_id / "snapshot"
    snapshot.mkdir()
    (snapshot / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(snapshot)], check=True)
    subprocess.run(["git", "-C", str(snapshot), "add", "-A"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(snapshot),
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "base",
        ],
        check=True,
    )
    completed = subprocess.run(
        ["git", "-C", str(snapshot), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def arm(
    arm_id: str,
    executor: str = "claude-code",
    gateway_alias: str = "anthropic/claude-sonnet-5-5",
    *,
    k: int = 1,
    provider: str = "anthropic",
    budget: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": arm_id,
        "executor": executor,
        "gateway_alias": gateway_alias,
        "data_class": "public",
        "budget": dict(budget or {"usd": 2.0, "wall_s": 1800, "max_turns": 60}),
        "k": k,
        "provider": provider,
    }


def write_arms(
    path: Path,
    arms: Sequence[Mapping[str, Any]] | None = None,
    providers: Mapping[str, int] | None = None,
    *,
    max_parallel: int = 2,
) -> Path:
    document = {
        "schema_version": "1",
        "max_parallel": max_parallel,
        "providers": dict(providers or {"anthropic": 2, "zai": 2, "local": 2}),
        "arms": list(arms or [arm("A1")]),
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


class FakeKeys:
    """Records the key lifecycle and returns a fixed spend payload."""

    def __init__(self, key: str = KEY, spend: Mapping[str, Any] | None = None) -> None:
        self.key = key
        self.spend_payload = dict(
            spend
            or {
                "spend_usd": 0.25,
                "requests": [
                    {
                        "model": "anthropic/claude-sonnet-5-5",
                        "prompt_tokens": 100,
                        "completion_tokens": 20,
                        "spend": 0.25,
                    }
                ],
            }
        )
        self.mints: list[tuple[str, float, int, str]] = []
        self.spends: list[str] = []
        self.revoked: list[str] = []
        self._lock = threading.Lock()

    def mint(self, data_class: str, budget_usd: float, ttl_sec: int, run_id: str) -> str:
        with self._lock:
            self.mints.append((data_class, budget_usd, ttl_sec, run_id))
        return self.key

    def spend(self, key: str) -> Mapping[str, Any]:
        with self._lock:
            self.spends.append(key)
        return dict(self.spend_payload)

    def revoke(self, key: str) -> None:
        with self._lock:
            self.revoked.append(key)


class FakeHarbor:
    """Copies a fixture trial into ``<jobs-dir>/<run-id>/`` and records concurrency."""

    def __init__(
        self,
        trial_source: Path | None = HARBOR_TRIAL,
        *,
        fail: bool = False,
        delay: float = 0.0,
    ) -> None:
        self.trial_source = trial_source
        self.fail = fail
        self.delay = delay
        self.calls = 0
        self.active = 0
        self.max_active = 0
        self.active_by_provider: dict[str, int] = {}
        self.max_by_provider: dict[str, int] = {}
        self.environments: list[dict[str, str]] = []
        self._lock = threading.Lock()

    def __call__(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        timeout: float,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[Any]:
        provider = _provider_of(argv)
        with self._lock:
            self.calls += 1
            self.environments.append(dict(env))
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.active_by_provider[provider] = self.active_by_provider.get(provider, 0) + 1
            self.max_by_provider[provider] = max(
                self.max_by_provider.get(provider, 0), self.active_by_provider[provider]
            )
        try:
            if self.delay:
                time.sleep(self.delay)
            if self.fail:
                raise RuntimeError("harbor exploded")
            if self.trial_source is not None:
                run_id = argv[argv.index("--job-name") + 1]
                jobs_dir = Path(argv[argv.index("--jobs-dir") + 1])
                target = jobs_dir / run_id / "trial__fake"
                shutil.rmtree(target, ignore_errors=True)
                shutil.copytree(self.trial_source, target)
            return subprocess.CompletedProcess(list(argv), 0, "", "")
        finally:
            with self._lock:
                self.active -= 1
                self.active_by_provider[provider] -= 1


def _provider_of(argv: Sequence[str]) -> str:
    model = argv[argv.index("--model") + 1]
    if "zai" in model:
        return "zai"
    if "local" in model:
        return "local"
    return "anthropic"


class FakeVerifier:
    """Writes a schema-valid verdict instead of running Docker."""

    def __init__(self, verdict: str = "reject", *, write: bool = True) -> None:
        self.verdict = verdict
        self.write = write
        self.calls: list[list[str]] = []

    def __call__(self, argv: Sequence[str], **_kwargs: Any) -> subprocess.CompletedProcess[Any]:
        self.calls.append(list(argv))
        if not self.write:
            return subprocess.CompletedProcess(list(argv), 20, "", "")
        out_dir = Path(argv[argv.index("--out-dir") + 1])
        diff = Path(argv[argv.index("--diff") + 1]).read_bytes()
        verdict = Verdict(
            run_id=argv[argv.index("--run-id") + 1],
            task_id=argv[argv.index("--task-id") + 1],
            arm=argv[argv.index("--arm") + 1],
            attempt=int(argv[argv.index("--attempt") + 1]),
            repetition=int(argv[argv.index("--repetition") + 1]),
            verdict=self.verdict,
            reason="fake verdict",
            diff_sha=sha256_label(diff),
            verify_cost_usd=0.01,
            category="empty_diff" if self.verdict == "reject" else None,
        )
        write_verdict(verdict, out_dir)
        code = {"accept": 0, "reject": 10, "cheat_suspected": 11, "error_infra": 20}[self.verdict]
        return subprocess.CompletedProcess(list(argv), code, "", "")


def write_verdict_doc(
    root: Path,
    run_id: str,
    *,
    arm_id: str = "A1",
    task_id: str = TASK_ID,
    repetition: int = 1,
    attempt: int = 1,
    verdict: str = "reject",
) -> Path:
    document: dict[str, Any] = {
        "schema_version": "1",
        "run_id": run_id,
        "task_id": task_id,
        "arm": arm_id,
        "attempt": attempt,
        "repetition": repetition,
        "verdict": verdict,
        "reason": "fixture",
        "verify_cost_usd": 0.0,
        "diff_sha": sha256_label(b""),
    }
    if verdict == "reject":
        document["category"] = "empty_diff"
    path = root / "verdicts" / f"{run_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def sample_run_document(run_id: str) -> dict[str, Any]:
    input_document = {
        "run_id": run_id,
        "executor": {"name": "opencode", "version": "1.19.5", "config_sha": DIGEST},
        "model": {"gateway_alias": "local/fixture"},
        "task": {"sha256": DIGEST},
    }
    return build_run_document(
        input_document=input_document,
        exit_decision=ExitDecision("done", "fixture"),
        diff=empty_diff(),
        gateway_usage=lambda _alias: {
            "tokens": {
                "input": 1,
                "output": 1,
                "cache_read": None,
                "cache_write": None,
                "reasoning": None,
            },
            "usd_real": 0.0,
            "usd_shadow": 0.0,
        },
        resolved_model="local/fixture",
        image_digest=DIGEST,
        timing=RunTiming(
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
            ended_at=datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
        ),
        diff_uri=f"runs/{run_id}.diff",
    )


def write_run_doc(root: Path, run_id: str, *, valid: bool = True) -> Path:
    path = root / "runs" / f"{run_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if valid:
        write_run_document(sample_run_document(run_id), path)
    else:
        path.write_text("{}", encoding="utf-8")
    return path
