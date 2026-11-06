"""Run the F0 matrix: every (arm x task x repetition) end to end.

``run`` builds the executor input for each planned attempt, takes the next key
from the pre-minted pool (or the key service), invokes Harbor with the pinned
command line and then verifies the resulting diff with ``python -m
factory.verifier``. It leaves the layout ``<out>/runs/<run_id>.json``,
``<out>/runs/<run_id>.diff`` and ``<out>/verdicts/<run_id>.json`` that
``factory.metrics.load.load_dataset`` reads. ``check`` enforces the F0-18 gate on
that layout.

Every side effect goes through ``Deps`` so the tests can use fakes: no Docker,
no network, no real key service. Key values are only ever placed in the child
environment; they are never printed, logged or written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter, deque
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote, urlsplit

import httpx
import jsonschema

from factory.adapters.abort import InvalidAbort, abort_path_for, validate_abort
from factory.adapters.config import GATEWAY_BASE_URL, AgentConfig, agent_config
from factory.adapters.diff import HostDiff, empty_diff, split_factory_files
from factory.adapters.exit import ERROR, ExitDecision, map_exit
from factory.adapters.harbor import build_harbor_command
from factory.adapters.output import (
    TOKEN_FIELDS,
    RunTiming,
    build_run_document,
    validate_run_document,
    write_run_document,
)
from factory.adapters.prompt import prompt_sha
from factory.gateway.client import FactoryKeysClient
from factory.normalize import normalize_text
from factory.tasks.to_harbor import snapshot_head, to_harbor, tree_digest
from factory.tasks.workdir import workdir_of
from factory.verifier.verdict import (
    ERROR_INFRA,
    Verdict,
    sha256_label,
    validate_document,
    write_verdict,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
INPUT_SCHEMA_PATH = REPO_ROOT / "schemas" / "executor-input.schema.json"
# Harbor agents that refuse to install executor CLIs over the network.
HARBOR_AGENTS_DIR = REPO_ROOT / "infra" / "harbor"

MAX_ATTEMPTS = 3
HARBOR_TIMEOUT_MARGIN_S = 600
KEY_TTL_MARGIN_S = 600
VERIFIER_TIMEOUT_S = 3600
IMAGE_INSPECT_TIMEOUT_S = 60
IMAGE_PULL_TIMEOUT_S = 1800
RUN_ID_MAX = 64
SPEND_SETTLE_S = 15.0
DEFAULT_KEY_BUDGET_USD = 2.0
DEFAULT_MANIFEST = REPO_ROOT / "tasks" / "public-v1.manifest.json"
GATEWAY_HTTP_TIMEOUT_S = 30.0

DATA_CLASSES = frozenset({"public", "internal", "client-product", "client-restricted"})
BUDGET_FIELDS = frozenset({"usd", "wall_s", "max_turns"})
BILLINGS = frozenset({"plan", "api"})
MODEL_LIMIT_FIELDS = frozenset({"context", "output"})
VERDICTS = frozenset({"accept", "reject", "cheat_suspected", "error_infra"})

STREAM_FILES = {
    "claude-code": "claude-code.txt",
    "codex": "codex.txt",
    "opencode": "opencode.txt",
}
MINI_TRAJECTORY = "mini-swe-agent.trajectory.json"

# Harbor exception types that mean the provider refused the run: an exhausted
# quota (``[1308] Usage limit reached``) is infrastructure, not an arm result.
RATE_LIMIT_EXCEPTIONS = frozenset({"ApiRateLimitError"})


class KeyClient(Protocol):
    """The slice of ``FactoryKeysClient`` the matrix uses."""

    def mint(self, data_class: str, budget_usd: float, ttl_sec: int, run_id: str) -> str: ...

    def spend(self, key: str) -> Mapping[str, Any]: ...

    def revoke(self, key: str) -> None: ...


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _gateway_get(url: str, headers: Mapping[str, str]) -> tuple[int, Any]:
    """GET ``url`` and return ``(status_code, decoded JSON or None)``."""
    response = httpx.get(url, headers=dict(headers), timeout=GATEWAY_HTTP_TIMEOUT_S)
    try:
        body: Any = response.json()
    except ValueError:
        body = None
    return response.status_code, body


def _key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class KeyPoolExhausted(RuntimeError):
    """The pre-minted pool has no unused key left."""


class ProviderRateLimit(RuntimeError):
    """The provider refused a run because a quota ran out; stop the matrix."""


class KeyPool:
    """Hand out keys minted in advance and read their spend from the gateway.

    ``mint`` never sees a master key: the owner mints the batch and this class
    only records which hashes were used, so a restart cannot hand out a key
    twice. The used set lives in ``used_file`` as ``{run_id: sha256(key)}``.
    """

    def __init__(
        self,
        keys_file: str | Path,
        used_file: str | Path,
        gateway_url: str,
        key_budget_usd: float = DEFAULT_KEY_BUDGET_USD,
        *,
        http: Callable[[str, Mapping[str, str]], tuple[int, Any]] = _gateway_get,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.keys_file = Path(keys_file)
        self.used_file = Path(used_file)
        self.gateway_url = gateway_url.rstrip("/").removesuffix("/v1")
        self.key_budget_usd = float(key_budget_usd)
        self._http = http
        self._sleep = sleep
        self._lock = threading.Lock()
        self._keys = _read_pool_keys(self.keys_file)
        self._used = _read_used_keys(self.used_file)
        self._used_hashes = set(self._used.values())

    def mint(self, data_class: str, budget_usd: float, ttl_sec: int, run_id: str) -> str:
        """Return the next unused key and record its hash under ``run_id``."""
        self.check_budget(budget_usd)
        with self._lock:
            for key in self._keys:
                digest = _key_hash(key)
                if digest in self._used_hashes:
                    continue
                self._used[run_id] = digest
                self._used_hashes.add(digest)
                _write_used_keys(self.used_file, self._used)
                return key
        raise KeyPoolExhausted(f"key pool {self.keys_file} has no unused keys left")

    def check_budget(self, budget_usd: float) -> None:
        if budget_usd > self.key_budget_usd:
            raise ValueError(
                f"arm budget ${budget_usd:.2f} exceeds the key budget "
                f"${self.key_budget_usd:.2f} given by --key-budget-usd"
            )

    def spend(self, key: str) -> Mapping[str, Any]:
        """Read the key's spend and, when available, its per-request tokens."""
        self._sleep(SPEND_SETTLE_S)
        status, body = self._http(
            f"{self.gateway_url}/key/info", {"Authorization": f"Bearer {key}"}
        )
        if status != 200 or not isinstance(body, Mapping):
            raise RuntimeError(f"gateway /key/info returned HTTP {status}")
        info = body.get("info")
        spend = (info if isinstance(info, Mapping) else body).get("spend")
        if not _is_number(spend):
            raise RuntimeError("gateway /key/info has no numeric spend")

        payload: dict[str, Any] = {"usd_real": max(0.0, float(spend)), "usd_shadow": 0.0}
        logs_url = f"{self.gateway_url}/spend/logs?api_key={quote(key, safe='')}&summarize=false"
        status, logs = self._http(logs_url, {"Authorization": f"Bearer {key}"})
        if status == 200 and isinstance(logs, list):
            payload["requests"] = [entry for entry in logs if isinstance(entry, Mapping)]
        return payload

    def revoke(self, key: str) -> None:
        """No-op: the owner deletes the whole batch by alias prefix."""


def _read_pool_keys(path: Path) -> list[str]:
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError as exc:
        raise ValueError(f"cannot read keys file {path}: {exc}") from exc
    if mode & 0o077:
        raise ValueError(f"keys file {path} must be mode 600 or stricter (found {mode:o})")
    keys: list[str] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        key = line.strip()
        if key and key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


def _read_used_keys(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not all(
        isinstance(run_id, str) and isinstance(digest, str) for run_id, digest in document.items()
    ):
        raise ValueError(f"{path} must map run ids to sha256 hashes")
    return dict(document)


def _write_used_keys(path: Path, used: Mapping[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(used, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


@dataclass(frozen=True)
class Deps:
    """The side-effecting steps of the matrix, replaced by fakes in tests."""

    key_client: KeyClient | None = None
    harbor: Callable[..., subprocess.CompletedProcess[Any]] = subprocess.run
    verifier: Callable[..., subprocess.CompletedProcess[Any]] = subprocess.run
    docker: Callable[..., subprocess.CompletedProcess[Any]] = subprocess.run
    clock: Callable[[], datetime] = _utcnow
    to_harbor: Callable[..., Path] = to_harbor
    key_http: Callable[[str, Mapping[str, str]], tuple[int, Any]] = _gateway_get
    key_sleep: Callable[[float], None] = time.sleep


@dataclass(frozen=True)
class Arm:
    id: str
    executor: str
    gateway_alias: str
    data_class: str
    budget: Mapping[str, Any]
    k: int
    provider: str
    model_limits: Mapping[str, int]
    billing: str


@dataclass(frozen=True)
class Matrix:
    arms: tuple[Arm, ...]
    providers: Mapping[str, int]
    max_parallel: int


@dataclass(frozen=True)
class PlannedRun:
    arm: Arm
    task_id: str
    repetition: int
    attempt: int
    run_id: str


@dataclass(frozen=True)
class ExistingVerdict:
    attempt: int
    verdict: str


@dataclass(frozen=True)
class _Loaded:
    """A JSON file that may be present but malformed."""

    document: dict[str, Any] | None


@dataclass
class _Attempt:
    run: PlannedRun
    task: Mapping[str, Any]
    input_document: dict[str, Any]
    holder: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Arms and tasks
# ---------------------------------------------------------------------------


def load_matrix(path: str | Path) -> Matrix:
    """Read and validate ``matrix/arms-v1.json``."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError("arms file must be a JSON object")

    providers_raw = raw.get("providers")
    if not isinstance(providers_raw, dict) or not providers_raw:
        raise ValueError("arms file needs a non-empty 'providers' object")
    providers: dict[str, int] = {}
    for name, limit in providers_raw.items():
        if not isinstance(name, str) or not name:
            raise ValueError("provider names must be non-empty strings")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError(f"provider {name!r} limit must be an integer >= 1")
        providers[name] = limit

    max_parallel = raw.get("max_parallel")
    if isinstance(max_parallel, bool) or not isinstance(max_parallel, int) or max_parallel < 1:
        raise ValueError("'max_parallel' must be an integer >= 1")

    arms_raw = raw.get("arms")
    if not isinstance(arms_raw, list) or not arms_raw:
        raise ValueError("arms file needs a non-empty 'arms' list")

    arms: list[Arm] = []
    seen: set[str] = set()
    for entry in arms_raw:
        arm = _load_arm(entry, providers)
        if arm.id in seen:
            raise ValueError(f"duplicate arm id {arm.id!r}")
        seen.add(arm.id)
        arms.append(arm)
    return Matrix(arms=tuple(arms), providers=providers, max_parallel=max_parallel)


def _load_arm(entry: Any, providers: Mapping[str, int]) -> Arm:
    if not isinstance(entry, dict):
        raise TypeError("each arm must be a JSON object")
    arm_id = entry.get("id")
    if not isinstance(arm_id, str) or not arm_id:
        raise ValueError("arm 'id' must be a non-empty string")
    executor = entry.get("executor")
    if not isinstance(executor, str):
        raise TypeError(f"arm {arm_id}: 'executor' must be a string")
    agent_config(executor)
    alias = entry.get("gateway_alias")
    if not isinstance(alias, str) or not alias:
        raise ValueError(f"arm {arm_id}: 'gateway_alias' must be a non-empty string")
    data_class = entry.get("data_class")
    if data_class not in DATA_CLASSES:
        raise ValueError(f"arm {arm_id}: unknown data_class {data_class!r}")
    provider = entry.get("provider")
    if provider not in providers:
        raise ValueError(f"arm {arm_id}: provider {provider!r} is not in 'providers'")
    k = entry.get("k")
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError(f"arm {arm_id}: 'k' must be an integer >= 1")

    budget = entry.get("budget")
    if not isinstance(budget, dict):
        raise TypeError(f"arm {arm_id}: 'budget' must be an object")
    unknown = sorted(set(budget) - BUDGET_FIELDS)
    if unknown:
        raise ValueError(f"arm {arm_id}: unknown budget fields: {', '.join(unknown)}")
    usd = budget.get("usd")
    if isinstance(usd, bool) or not isinstance(usd, (int, float)) or usd <= 0:
        raise ValueError(f"arm {arm_id}: budget.usd must be a positive number")
    wall_s = budget.get("wall_s")
    if isinstance(wall_s, bool) or not isinstance(wall_s, int) or wall_s < 1:
        raise ValueError(f"arm {arm_id}: budget.wall_s must be an integer >= 1")
    if "max_turns" in budget:
        turns = budget["max_turns"]
        if isinstance(turns, bool) or not isinstance(turns, int) or turns < 1:
            raise ValueError(f"arm {arm_id}: budget.max_turns must be an integer >= 1")

    billing = entry.get("billing")
    if billing not in BILLINGS:
        allowed = ", ".join(sorted(BILLINGS))
        raise ValueError(f"arm {arm_id}: 'billing' must be one of: {allowed}")

    limits = entry.get("model_limits")
    if not isinstance(limits, dict):
        raise TypeError(f"arm {arm_id}: 'model_limits' must be an object")
    unknown = sorted(set(limits) - MODEL_LIMIT_FIELDS)
    if unknown:
        raise ValueError(f"arm {arm_id}: unknown model_limits fields: {', '.join(unknown)}")
    model_limits: dict[str, int] = {}
    for limit_field in sorted(MODEL_LIMIT_FIELDS):
        value = limits.get(limit_field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"arm {arm_id}: model_limits.{limit_field} must be an integer >= 1")
        model_limits[limit_field] = value

    return Arm(
        id=arm_id,
        executor=executor,
        gateway_alias=alias,
        data_class=data_class,
        budget=dict(budget),
        k=k,
        provider=provider,
        model_limits=model_limits,
        billing=billing,
    )


def valid_task_ids(store: str | Path) -> list[str]:
    """Task ids the inventory counts: ``hidden/<id>/revalidation.json`` says valid."""
    hidden = Path(store) / "hidden"
    if not hidden.is_dir():
        return []
    return [
        task_dir.name
        for task_dir in sorted(path for path in hidden.iterdir() if path.is_dir())
        if _revalidated(task_dir / "revalidation.json")
    ]


def manifest_task_ids(path: str | Path) -> list[str]:
    """Read the ``task_id`` list of the public task manifest."""
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise TypeError(f"{path} must be a JSON object")
    tasks = document.get("tasks")
    if not isinstance(tasks, list):
        raise TypeError(f"{path} needs a 'tasks' list")
    task_ids: list[str] = []
    for entry in tasks:
        task_id = entry.get("task_id") if isinstance(entry, Mapping) else None
        if not isinstance(task_id, str) or not task_id:
            raise ValueError(f"{path}: every task needs a non-empty 'task_id'")
        if task_id not in task_ids:
            task_ids.append(task_id)
    return task_ids


def select_task_ids(store: str | Path, manifest: str | Path, requested: Sequence[str]) -> list[str]:
    """The manifest's tasks, each of which must be valid in the store."""
    known = valid_task_ids(store)
    task_ids = manifest_task_ids(manifest)
    missing = sorted(set(task_ids) - set(known))
    if missing:
        raise ValueError(f"manifest tasks not valid in the store: {', '.join(missing)}")
    return _select(task_ids, requested, "task")


def _revalidated(path: Path) -> bool:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(document, dict) and document.get("valid") is True


def _select(values: Sequence[str], requested: Sequence[str], kind: str) -> list[str]:
    if not requested:
        return list(values)
    missing = sorted(set(requested) - set(values))
    if missing:
        raise ValueError(f"unknown {kind}: {', '.join(missing)}")
    wanted = set(requested)
    return [value for value in values if value in wanted]


def _select_arms(arms: Sequence[Arm], requested: Sequence[str]) -> list[Arm]:
    if not requested:
        return list(arms)
    by_id = {arm.id: arm for arm in arms}
    missing = sorted(set(requested) - set(by_id))
    if missing:
        raise ValueError(f"unknown arm: {', '.join(missing)}")
    wanted = set(requested)
    return [arm for arm in arms if arm.id in wanted]


# ---------------------------------------------------------------------------
# Planning and idempotency
# ---------------------------------------------------------------------------


def run_id_for(arm_id: str, task_id: str, repetition: int, attempt: int) -> str:
    """Deterministic, schema-valid run id for one attempt."""
    prefix = re.sub(r"[^a-z0-9-]+", "-", arm_id.lower()).strip("-") or "arm"
    suffix = f"-r{repetition}-a{attempt}"
    clean = re.sub(r"[^a-z0-9-]+", "-", task_id.lower()).strip("-") or "task"
    available = RUN_ID_MAX - len(prefix) - len(suffix) - 1
    if len(clean) > available:
        digest = hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:8]
        keep = max(1, available - len(digest) - 1)
        clean = f"{clean[:keep].rstrip('-')}-{digest}"
    return f"{prefix}-{clean}{suffix}"


def scan_verdicts(directory: str | Path) -> dict[tuple[str, str, int], list[ExistingVerdict]]:
    """Group readable verdicts by (arm, task, repetition) for idempotency."""
    grouped: dict[tuple[str, str, int], list[ExistingVerdict]] = {}
    directory = Path(directory)
    if not directory.is_dir():
        return grouped
    for path in sorted(directory.glob("*.json")):
        document = _read_json(path)
        if document is None:
            continue
        arm = document.get("arm")
        task_id = document.get("task_id")
        repetition = document.get("repetition")
        attempt = document.get("attempt")
        verdict = document.get("verdict")
        if not (
            isinstance(arm, str)
            and isinstance(task_id, str)
            and isinstance(repetition, int)
            and not isinstance(repetition, bool)
            and isinstance(attempt, int)
            and not isinstance(attempt, bool)
            and isinstance(verdict, str)
        ):
            continue
        grouped.setdefault((arm, task_id, repetition), []).append(
            ExistingVerdict(attempt=attempt, verdict=verdict)
        )
    return grouped


def next_attempt(
    existing: Mapping[tuple[str, str, int], Sequence[ExistingVerdict]],
    arm_id: str,
    task_id: str,
    repetition: int,
) -> int | None:
    """1 for a missing cell, ``attempt + 1`` after ``error_infra``, None when done."""
    attempts = existing.get((arm_id, task_id, repetition), ())
    if not attempts:
        return 1
    latest = max(attempts, key=lambda item: item.attempt)
    if latest.verdict != ERROR_INFRA:
        return None
    if latest.attempt >= MAX_ATTEMPTS:
        return None
    return latest.attempt + 1


def build_plan(
    arms: Sequence[Arm],
    task_ids: Sequence[str],
    k_override: int | None,
    existing: Mapping[tuple[str, str, int], Sequence[ExistingVerdict]],
) -> list[PlannedRun]:
    plan: list[PlannedRun] = []
    for arm in arms:
        k = arm.k if k_override is None else k_override
        for task_id in task_ids:
            for repetition in range(1, k + 1):
                attempt = next_attempt(existing, arm.id, task_id, repetition)
                if attempt is None:
                    continue
                plan.append(
                    PlannedRun(
                        arm=arm,
                        task_id=task_id,
                        repetition=repetition,
                        attempt=attempt,
                        run_id=run_id_for(arm.id, task_id, repetition, attempt),
                    )
                )
    return plan


# ---------------------------------------------------------------------------
# Executor input
# ---------------------------------------------------------------------------


def load_task_document(store: str | Path, task_id: str) -> dict[str, Any]:
    path = Path(store) / "visible" / task_id / "factory.task.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise TypeError(f"{path} must be a JSON object")
    return document


def build_input_document(
    run: PlannedRun, store: str | Path, task: Mapping[str, Any]
) -> dict[str, Any]:
    visible = Path(store) / "visible" / run.task_id
    config = agent_config(run.arm.executor)
    document = {
        "schema_version": "0.1",
        "run_id": run.run_id,
        "attempt": run.attempt,
        "repo": {
            "url": _repo_url(task, run.task_id),
            "commit": task["repo"]["commit"],
            "snapshot": "fresh-init",
        },
        "task": {
            "format": "openspec",
            "path": f"openspec/changes/{run.task_id}/",
            "sha256": _tree_sha256(visible),
            "class": task["class"],
            "visible_tests": list(task["visible_tests"]["ids"]),
        },
        "budget": dict(run.arm.budget),
        "executor": {
            "name": run.arm.executor,
            "version": config.cli_version,
            "config_sha": _config_sha(config),
        },
        "model": {"gateway_alias": run.arm.gateway_alias},
        "prompt": {"template_id": "base-v1", "sha256": prompt_sha()},
        "data_class": run.arm.data_class,
        "abort_path": abort_path_for(workdir_of(task)),
    }
    _validate_input(document)
    return document


def _repo_url(task: Mapping[str, Any], task_id: str) -> str:
    source = task.get("source")
    if isinstance(source, Mapping):
        dataset = source.get("dataset")
        if isinstance(dataset, str) and dataset:
            return dataset
    return task_id


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] == "snapshot":
            continue
        if path.is_symlink():
            raise ValueError(f"task directory contains a symlink: {path}")
        if path.is_file():
            digest.update(relative.as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _config_sha(config: AgentConfig) -> str:
    payload = {
        "name": config.name,
        "harbor_agent": config.harbor_agent,
        "cli_version": config.cli_version,
        "model_prefix": config.model_prefix,
        "raw_format": config.raw_format,
        "env_names": list(config.env_names),
        "image_lines": list(config.image_lines),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def _input_validator() -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(
        json.loads(INPUT_SCHEMA_PATH.read_text(encoding="utf-8"))
    )


def _validate_input(document: Mapping[str, Any]) -> None:
    try:
        _input_validator().validate(document)
    except jsonschema.ValidationError as exc:
        location = "/".join(str(part) for part in exc.absolute_path) or "(root)"
        raise ValueError(f"executor input {location}: {exc.message}") from exc


def _harbor_input(document: Mapping[str, Any]) -> dict[str, Any]:
    """Drop a provider prefix the executor itself will add again."""
    config = agent_config(document["executor"]["name"])
    alias = document["model"]["gateway_alias"].removeprefix(config.model_prefix)
    return {**document, "model": {"gateway_alias": alias}}


def _wall_s(arm: Arm) -> int:
    return int(arm.budget["wall_s"])


def _harbor_task_dir(work: Path, executor: str, wall_s: int, task_id: str) -> Path:
    """Harbor task dir per (executor, arm wall clock, task).

    Arms with the same executor and different wall clocks must never share a
    converted task, or the first conversion's ``[agent] timeout_sec`` sticks.
    """
    return work / "harbor" / f"{executor}-t{wall_s}" / task_id


def _harbor_command(run: PlannedRun, document: Mapping[str, Any], work: Path, gateway_url: str):
    return build_harbor_command(
        _harbor_input(document),
        task_dir=_harbor_task_dir(work, run.arm.executor, _wall_s(run.arm), run.task_id),
        jobs_dir=work / "jobs",
        gateway_url=gateway_url,
        model_limits=run.arm.model_limits,
    )


# ---------------------------------------------------------------------------
# Key environment
# ---------------------------------------------------------------------------


def run_environment(
    executor: str, key: str, alias: str, gateway_url: str = GATEWAY_BASE_URL
) -> dict[str, str]:
    """Values for the environment names Harbor needs; never logged."""
    values: dict[str, str] = {}
    gateway_root = gateway_url.removesuffix("/v1")
    for name in agent_config(executor).env_names:
        if name in {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "FACTORY_GATEWAY_KEY", "MSWEA_API_KEY"}:
            values[name] = key
        elif name == "ANTHROPIC_BASE_URL":
            values[name] = gateway_root
        elif name in {"OPENAI_BASE_URL", "OPENAI_API_BASE"}:
            values[name] = gateway_url
        elif name == "ANTHROPIC_DEFAULT_HAIKU_MODEL":
            values[name] = alias
        elif name in {"DISABLE_AUTOUPDATER", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"}:
            values[name] = "1"
        elif name == "CLAUDE_CODE_ENABLE_TELEMETRY":
            values[name] = "0"
        elif name == "MSWEA_COST_TRACKING":
            values[name] = "ignore_errors"
    return values


def _redact(text: str, *secrets: str | None) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "<redacted>")
    return text


def harbor_environment(
    executor: str, key: str, alias: str, gateway_url: str = GATEWAY_BASE_URL
) -> dict[str, str]:
    """The child env for ``harbor run``, with the pinned agents on ``PYTHONPATH``."""
    env = os.environ | run_environment(executor, key, alias, gateway_url)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join(part for part in (str(HARBOR_AGENTS_DIR), existing) if part)
    return env


# ---------------------------------------------------------------------------
# One attempt
# ---------------------------------------------------------------------------


_IMAGE_LOCKS: dict[str, threading.Lock] = {}
_IMAGE_LOCKS_GUARD = threading.Lock()


def _image_lock(image: str) -> threading.Lock:
    """One lock per image so parallel runs of a task share a single pull."""
    with _IMAGE_LOCKS_GUARD:
        return _IMAGE_LOCKS.setdefault(image, threading.Lock())


def ensure_task_image(image: str, deps: Deps) -> None:
    """Make ``image`` present locally, pulling it once when Docker cannot find it.

    Harbor builds the agent image FROM the task image but does not leave the
    task image tagged locally, and the verifier's sandbox never pulls (it does
    not touch the network). Pulling here, under a per-image lock, keeps that
    contract without pulling the same image once per parallel run.
    """
    with _image_lock(image):
        present = deps.docker(
            ["docker", "image", "inspect", image],
            capture_output=True,
            text=True,
            timeout=IMAGE_INSPECT_TIMEOUT_S,
        )
        if present.returncode == 0:
            return
        pulled = deps.docker(
            ["docker", "pull", image],
            capture_output=True,
            text=True,
            timeout=IMAGE_PULL_TIMEOUT_S,
        )
        if pulled.returncode != 0:
            detail = (pulled.stderr or pulled.stdout or "").strip()
            raise RuntimeError(f"docker pull {image} failed: {detail[:300]}")


def _quarantine_job_dir(job_dir: Path, run_id: str, now: datetime) -> None:
    """Keep Harbor from resuming a finished trial left in this run's job dir.

    A re-run keeps the same ``run_id`` and therefore the same
    ``work/jobs/<run_id>``, where Harbor finds the previous trial and returns it
    without running the agent. Leave the old dir where it is but out of reach.
    """
    if not job_dir.is_dir() or not any(job_dir.iterdir()):
        return
    stale = job_dir.with_name(f"{job_dir.name}.stale-{now.strftime('%Y%m%dT%H%M%SZ')}")
    job_dir.rename(stale)
    print(f"{run_id}: previous job dir moved to {stale}", file=sys.stderr)


def _execute_attempt(
    attempt: _Attempt, args: argparse.Namespace, deps: Deps, client: KeyClient
) -> None:
    run = attempt.run
    started = deps.clock()
    command = _harbor_command(run, attempt.input_document, args.work, args.gateway_url)
    _quarantine_job_dir(args.work / "jobs" / run.run_id, run.run_id, started)
    key = client.mint(
        run.arm.data_class,
        float(run.arm.budget["usd"]),
        int(run.arm.budget["wall_s"]) + KEY_TTL_MARGIN_S,
        run.run_id,
    )
    attempt.holder["key"] = key
    try:
        timed_out = False
        try:
            deps.harbor(
                command.argv,
                env=harbor_environment(run.arm.executor, key, command.model, args.gateway_url),
                timeout=int(run.arm.budget["wall_s"]) + HARBOR_TIMEOUT_MARGIN_S,
                capture_output=True,
                text=True,
            )
        except subprocess.TimeoutExpired:
            timed_out = True

        spend = client.spend(key)
        ended = deps.clock()
        trial = _trial_dir(args.work / "jobs" / run.run_id)
        result = _read_json(trial / "result.json") if trial is not None else None
        stream, trajectory = _trial_artifacts(trial, run.arm.executor)
        patch = _read_bytes(trial / "verifier" / "diff.patch") if trial is not None else b""
        patch, factory_files = split_factory_files(patch)
        abort = _abort_document(factory_files)
        host_diff = _host_diff(patch)

        setup_failure = _setup_failure(result)
        rate_limit = _rate_limit_failure(result)
        infra_failure = rate_limit if rate_limit is not None else setup_failure
        if infra_failure is not None:
            decision = ExitDecision(ERROR, _redact(infra_failure, key))
        else:
            decision = map_exit(
                executor=run.arm.executor,
                abort=abort,
                result=result,
                timed_out=timed_out,
                stream=stream,
                trajectory=trajectory,
            )
        usage = _gateway_usage(spend, run.arm.billing)
        if not isinstance(spend.get("requests"), list):
            agent_tokens = _agent_reported_tokens(run.arm.executor, run.run_id, stream, trajectory)
            if agent_tokens is not None:
                usage["tokens"] = agent_tokens
        run_document = build_run_document(
            input_document=attempt.input_document,
            exit_decision=decision,
            diff=host_diff,
            gateway_usage=lambda _alias: usage,
            resolved_model=_resolved_model(spend, command.model),
            image_digest=_image_digest(attempt.task),
            timing=_timing(started, ended),
            abort=abort,
            agent_reported_usd=_agent_reported_usd(result),
            diff_uri=f"runs/{run.run_id}.diff",
        )

        diff_path = args.out / "runs" / f"{run.run_id}.diff"
        diff_path.parent.mkdir(parents=True, exist_ok=True)
        diff_path.write_bytes(host_diff.patch)
        run_path = args.out / "runs" / f"{run.run_id}.json"
        write_run_document(run_document, run_path)

        if trial is None or result is None or infra_failure is not None:
            _write_infra_verdict(
                run,
                args,
                reason=decision.detail,
                diff_sha=host_diff.sha256,
                duration_s=_wall_seconds(started, ended),
            )
            if rate_limit is not None:
                raise ProviderRateLimit(decision.detail)
            return

        _verify(attempt, args, deps, run_path, diff_path, host_diff.sha256, started, ended)
    finally:
        try:
            client.revoke(key)
        except Exception as exc:  # noqa: BLE001 - a failed revoke must not hide the run
            message = _redact(f"{type(exc).__name__}: {exc}", key)
            print(f"{run.run_id}: revoke failed: {message}", file=sys.stderr)


def _verify(
    attempt: _Attempt,
    args: argparse.Namespace,
    deps: Deps,
    run_path: Path,
    diff_path: Path,
    diff_sha: str,
    started: datetime,
    ended: datetime,
) -> None:
    run = attempt.run
    try:
        ensure_task_image(attempt.task["image"], deps)
    except Exception as exc:  # noqa: BLE001 - an infra failure becomes error_infra
        _write_infra_verdict(
            run,
            args,
            reason=f"{type(exc).__name__}: {exc}",
            diff_sha=diff_sha,
            duration_s=_wall_seconds(started, ended),
        )
        return

    out_dir = args.work / "verifier" / run.run_id
    shutil.rmtree(out_dir, ignore_errors=True)
    argv = [
        sys.executable,
        "-m",
        "factory.verifier",
        "--task-store",
        str(args.store),
        "--task-id",
        run.task_id,
        "--diff",
        str(diff_path),
        "--mirror",
        str(args.store / "visible" / run.task_id / "snapshot"),
        "--base-commit",
        snapshot_head(args.store / "visible" / run.task_id),
        "--run",
        str(run_path),
        "--run-id",
        run.run_id,
        "--arm",
        run.arm.id,
        "--repetition",
        str(run.repetition),
        "--attempt",
        str(run.attempt),
        "--out-dir",
        str(out_dir),
    ]
    failure: str | None = None
    try:
        deps.verifier(
            argv,
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            timeout=VERIFIER_TIMEOUT_S,
        )
    except Exception as exc:  # noqa: BLE001 - an infra failure becomes error_infra
        failure = f"{type(exc).__name__}: {exc}"

    produced = out_dir / "verdict.json"
    if produced.is_file():
        _store_verdict(produced, args.out / "verdicts" / f"{run.run_id}.json")
        shutil.rmtree(out_dir, ignore_errors=True)
        return

    _write_infra_verdict(
        run,
        args,
        reason=failure or "verifier produced no verdict",
        diff_sha=diff_sha,
        duration_s=_wall_seconds(started, ended),
    )


def _record_infra(
    run: PlannedRun,
    args: argparse.Namespace,
    deps: Deps,
    task: Mapping[str, Any],
    reason: str,
) -> None:
    """Guarantee a schema-valid run document and an ``error_infra`` verdict."""
    run_path = args.out / "runs" / f"{run.run_id}.json"
    verdict_path = args.out / "verdicts" / f"{run.run_id}.json"
    if not run_path.exists():
        started = deps.clock()
        ended = deps.clock()
        document = build_input_document(run, args.store, task)
        artifact = empty_diff()
        run_document = build_run_document(
            input_document=document,
            exit_decision=ExitDecision("error", reason),
            diff=artifact,
            gateway_usage=lambda _alias: _zero_usage(),
            resolved_model=run.arm.gateway_alias,
            image_digest=_image_digest(task),
            timing=_timing(started, ended),
            diff_uri=f"runs/{run.run_id}.diff",
        )
        diff_path = args.out / "runs" / f"{run.run_id}.diff"
        diff_path.parent.mkdir(parents=True, exist_ok=True)
        diff_path.write_bytes(b"")
        write_run_document(run_document, run_path)
    if not verdict_path.exists():
        diff_sha = empty_diff().sha256
        existing = _read_json(run_path)
        if existing is not None:
            diff = existing.get("diff")
            if isinstance(diff, Mapping) and isinstance(diff.get("sha256"), str):
                diff_sha = diff["sha256"]
        _write_infra_verdict(
            run,
            args,
            reason=reason,
            diff_sha=diff_sha,
            duration_s=0.0,
        )


def _write_infra_verdict(
    run: PlannedRun, args: argparse.Namespace, *, reason: str, diff_sha: str, duration_s: float
) -> None:
    _store_run_verdict(
        run,
        args,
        verdict=ERROR_INFRA,
        reason=reason,
        diff_sha=diff_sha,
        duration_s=duration_s,
    )


def _store_run_verdict(
    run: PlannedRun,
    args: argparse.Namespace,
    *,
    verdict: str,
    reason: str,
    diff_sha: str,
    duration_s: float,
    category: str | None = None,
) -> None:
    document = Verdict(
        run_id=run.run_id,
        task_id=run.task_id,
        arm=run.arm.id,
        attempt=run.attempt,
        repetition=run.repetition,
        verdict=verdict,
        reason=reason[:1000],
        diff_sha=diff_sha,
        duration_s=duration_s,
        category=category,
    )
    temp_dir = args.work / "verifier" / run.run_id
    write_verdict(document, temp_dir)
    _store_verdict(temp_dir / "verdict.json", args.out / "verdicts" / f"{run.run_id}.json")
    shutil.rmtree(temp_dir, ignore_errors=True)


def _store_verdict(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))


# ---------------------------------------------------------------------------
# Harbor job artifacts
# ---------------------------------------------------------------------------


def _trial_dir(job_dir: Path) -> Path | None:
    if not job_dir.is_dir():
        return None
    candidates = [
        path.parent
        for path in job_dir.glob("*/result.json")
        if path.parent.is_dir() and not path.parent.name.startswith(".")
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime_ns)


def _trial_artifacts(
    trial: Path | None, executor: str
) -> tuple[bytes | None, Mapping[str, Any] | None]:
    if trial is None:
        return None, None
    agent_dir = trial / "agent"
    if executor == "mini-swe-agent":
        return None, _read_json(agent_dir / MINI_TRAJECTORY)
    name = STREAM_FILES.get(executor)
    if name is None:
        return None, None
    data = _read_bytes(agent_dir / name)
    return (data or None), None


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError:
        return b""


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return document if isinstance(document, dict) else None


def _abort_document(factory_files: Mapping[str, bytes]) -> dict[str, Any] | None:
    """The validated abort document the patch added, or ``None`` when absent or invalid."""
    data = factory_files.get(".factory/abort.json")
    if data is None:
        return None
    try:
        document = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return None
    try:
        return validate_abort(document)
    except InvalidAbort:
        return None


def _host_diff(patch: bytes) -> HostDiff:
    if not patch:
        return empty_diff()
    files, added, removed = _patch_stats(patch)
    return HostDiff(
        patch=patch,
        sha256=sha256_label(patch),
        files_changed=files,
        lines_added=added,
        lines_removed=removed,
    )


def _patch_stats(patch: bytes) -> tuple[int, int, int]:
    """File and line counts of a unified diff, parsed by git itself."""
    try:
        with tempfile.TemporaryDirectory(prefix="factory-diff-stats-") as tmp:
            path = Path(tmp) / "diff.patch"
            path.write_bytes(patch)
            completed = subprocess.run(
                ["git", "apply", "--numstat", "-z", "--", str(path)],
                capture_output=True,
                check=False,
                timeout=120,
            )
    except (OSError, subprocess.SubprocessError):
        return 0, 0, 0
    if completed.returncode != 0:
        return 0, 0, 0
    files = added = removed = 0
    for record in completed.stdout.split(b"\0"):
        if not record:
            continue
        fields = record.split(b"\t", 2)
        if len(fields) != 3:
            return 0, 0, 0
        files += 1
        if fields[0] == b"-" and fields[1] == b"-":
            continue
        try:
            added += int(fields[0])
            removed += int(fields[1])
        except ValueError:
            return 0, 0, 0
    return files, added, removed


def _exception_reason(result: Mapping[str, Any] | None) -> tuple[str, str] | None:
    """``(exception_type, message)`` when Harbor recorded an exception."""
    if not isinstance(result, Mapping):
        return None
    info = result.get("exception_info")
    if not isinstance(info, Mapping):
        return None
    exception_type = info.get("exception_type")
    message = info.get("exception_message")
    kind = exception_type if isinstance(exception_type, str) else "exception"
    text = message if isinstance(message, str) else ""
    return kind, text


def _rate_limit_failure(result: Mapping[str, Any] | None) -> str | None:
    """``exception_type: message`` when the provider rate-limited the run.

    Unlike a setup failure this applies whether or not the agent had started:
    the arm got no chance to produce a result.
    """
    reason = _exception_reason(result)
    if reason is None or reason[0] not in RATE_LIMIT_EXCEPTIONS:
        return None
    return f"{reason[0]}: {reason[1][:300]}"


def _setup_failure(result: Mapping[str, Any] | None) -> str | None:
    """``exception_type: message`` when Harbor failed before the agent started.

    A trial whose agent never ran (no ``agent_execution`` timing) failed in the
    environment or agent setup; that is infrastructure, not an arm result. An
    exception after the agent ran keeps the normal ``map_exit`` mapping.
    """
    reason = _exception_reason(result)
    if not isinstance(result, Mapping) or reason is None:
        return None
    execution = result.get("agent_execution")
    if isinstance(execution, Mapping) and execution.get("started_at") is not None:
        return None
    return f"{reason[0]}: {reason[1][:300]}"


def _agent_reported_usd(result: Mapping[str, Any] | None) -> float | None:
    if not isinstance(result, Mapping):
        return None
    contexts: list[Mapping[str, Any]] = []
    agent_result = result.get("agent_result")
    if isinstance(agent_result, Mapping):
        contexts.append(agent_result)
    steps = result.get("step_results")
    if isinstance(steps, list):
        for step in steps:
            if isinstance(step, Mapping):
                step_result = step.get("agent_result")
                if isinstance(step_result, Mapping):
                    contexts.append(step_result)
    for context in contexts:
        value = context.get("cost_usd")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def _gateway_usage(payload: Mapping[str, Any], billing: str = "api") -> dict[str, Any]:
    tokens: dict[str, Any] = {
        "input": 0,
        "output": 0,
        "cache_read": None,
        "cache_write": None,
        "reasoning": None,
    }
    requests = payload.get("requests")
    if isinstance(requests, list):
        for entry in requests:
            if not isinstance(entry, Mapping):
                continue
            tokens["input"] += _as_int(entry.get("prompt_tokens"))
            tokens["output"] += _as_int(entry.get("completion_tokens"))
    usd_real = payload.get("usd_real")
    if not _is_number(usd_real):
        usd_real = payload.get("spend_usd", 0.0)
    usd_shadow = payload.get("usd_shadow", 0.0)
    real = max(0.0, float(usd_real)) if _is_number(usd_real) else 0.0
    shadow = max(0.0, float(usd_shadow)) if _is_number(usd_shadow) else 0.0
    if billing == "plan":
        # Flat-rate plans and local models cost the owner nothing per token: the
        # gateway's figure is a list-price shadow cost.
        shadow, real = real + shadow, 0.0
    else:
        shadow = 0.0
    return {
        "tokens": tokens,
        "usd_real": real,
        "usd_shadow": shadow,
    }


def _agent_reported_tokens(
    executor: str,
    run_id: str,
    stream: bytes | None,
    trajectory: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Sum the agent's own usage events when the gateway has no logs.

    Per-request logs need a virtual key with logging enabled; a plain key has
    none, but the executor stream still reports what it used. The normalizers
    own the per-executor format, so this only adds the totals up.
    """
    if executor == "mini-swe-agent":
        if trajectory is None:
            return None
        text = json.dumps(trajectory)
    else:
        if stream is None:
            return None
        text = stream.decode("utf-8", errors="replace")
    try:
        normalized = normalize_text(executor, run_id, text)
    except (TypeError, ValueError):
        return None
    totals: dict[str, int] = {}
    for event in normalized.events:
        if event.kind != "usage" or not event.tokens:
            continue
        for token_field in TOKEN_FIELDS:
            value = event.tokens.get(token_field)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                totals[token_field] = totals.get(token_field, 0) + value
    if not totals:
        return None
    tokens: dict[str, Any] = {field: totals.get(field) for field in TOKEN_FIELDS}
    tokens["input"] = totals.get("input", 0)
    tokens["output"] = totals.get("output", 0)
    tokens["source"] = "agent"
    return tokens


def _zero_usage() -> dict[str, Any]:
    return {
        "tokens": {
            "input": 0,
            "output": 0,
            "cache_read": None,
            "cache_write": None,
            "reasoning": None,
        },
        "usd_real": 0.0,
        "usd_shadow": 0.0,
    }


def _resolved_model(payload: Mapping[str, Any], fallback: str) -> str:
    requests = payload.get("requests")
    if isinstance(requests, list):
        models = [
            entry["model"]
            for entry in requests
            if isinstance(entry, Mapping) and isinstance(entry.get("model"), str) and entry["model"]
        ]
        if models:
            return Counter(models).most_common(1)[0][0]
    return fallback


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _as_int(value: Any) -> int:
    if not _is_number(value):
        return 0
    return int(max(0, value))


def _timing(started: datetime, ended: datetime) -> RunTiming:
    return RunTiming(started_at=started, ended_at=ended)


def _wall_seconds(started: datetime, ended: datetime) -> float:
    return max(0.0, (ended - started).total_seconds())


def _image_digest(task: Mapping[str, Any]) -> str:
    image = task["image"]
    return image.rsplit("@", 1)[-1]


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def _run_command(args: argparse.Namespace, deps: Deps) -> int:
    matrix = load_matrix(args.arms)
    task_ids = select_task_ids(args.store, args.manifest, args.task)
    arms = _select_arms(matrix.arms, args.arm)
    matrix = replace(matrix, arms=tuple(arms))

    existing = scan_verdicts(args.out / "verdicts")
    plan = build_plan(matrix.arms, task_ids, args.k, existing)
    if not plan:
        print("nothing to run")
        return 0

    planned_tasks = sorted({run.task_id for run in plan})
    planned_executor_walls = sorted({(run.arm.executor, _wall_s(run.arm)) for run in plan})
    task_documents = {task_id: load_task_document(args.store, task_id) for task_id in planned_tasks}

    if args.dry_run:
        for run in plan:
            document = build_input_document(run, args.store, task_documents[run.task_id])
            command = _harbor_command(run, document, args.work, args.gateway_url)
            print(run.run_id)
            print(shlex.join(command.argv))
        return 0

    (args.out / "runs").mkdir(parents=True, exist_ok=True)
    (args.out / "verdicts").mkdir(parents=True, exist_ok=True)
    client, owns_client = _key_client(args, deps)
    try:
        if isinstance(client, KeyPool):
            for run in plan:
                client.check_budget(float(run.arm.budget["usd"]))
        converted, conversion_errors = _convert_tasks(
            planned_tasks, planned_executor_walls, args, deps
        )
        semaphores = {
            provider: threading.Semaphore(limit) for provider, limit in matrix.providers.items()
        }
        stop = threading.Event()
        failures = 0
        skipped = 0
        pending = deque(plan)
        with ThreadPoolExecutor(max_workers=matrix.max_parallel) as pool:
            futures: dict[Future[bool], PlannedRun] = {}
            while pending or futures:
                while pending and len(futures) < matrix.max_parallel and not stop.is_set():
                    run = pending.popleft()
                    future = pool.submit(
                        _run_one,
                        run,
                        task_documents[run.task_id],
                        args,
                        deps,
                        client,
                        semaphores,
                        converted,
                        conversion_errors,
                        stop,
                    )
                    futures[future] = run
                if not futures:
                    break
                done, _ = wait(futures, return_when=FIRST_COMPLETED)
                for future in done:
                    futures.pop(future)
                    try:
                        ran = future.result()
                    except KeyPoolExhausted as exc:
                        stop.set()
                        print(f"key pool exhausted: {_redact(str(exc))}", file=sys.stderr)
                    except ProviderRateLimit as exc:
                        stop.set()
                        print(f"provider rate limit: {exc}", file=sys.stderr)
                    except Exception as exc:  # noqa: BLE001 - report and keep accounting the rest
                        failures += 1
                        print(f"run failed to record: {_redact(str(exc))}", file=sys.stderr)
                    else:
                        skipped += 0 if ran else 1
        if stop.is_set():
            print(f"stopped: {skipped + len(pending)} runs not started", file=sys.stderr)
            return 1
        return 0 if failures == 0 else 1
    finally:
        if owns_client:
            close = getattr(client, "close", None)
            if close is not None:
                close()


def _key_client(args: argparse.Namespace, deps: Deps) -> tuple[KeyClient, bool]:
    if deps.key_client is not None:
        return deps.key_client, False
    if args.keys_file is not None:
        pool = KeyPool(
            args.keys_file,
            args.work / "keys-used.json",
            args.gateway_url,
            args.key_budget_usd,
            http=deps.key_http,
            sleep=deps.key_sleep,
        )
        return pool, False
    url = os.environ.get("FACTORY_KEYS_URL")
    token = os.environ.get("FACTORY_KEYS_TOKEN")
    if not url or not token:
        raise SystemExit("FACTORY_KEYS_URL and FACTORY_KEYS_TOKEN are required")
    return FactoryKeysClient(url, token), True


def _convert_tasks(
    task_ids: Sequence[str],
    executor_walls: Sequence[tuple[str, int]],
    args: argparse.Namespace,
    deps: Deps,
) -> tuple[dict[tuple[str, int, str], Path], dict[tuple[str, int, str], str]]:
    converted: dict[tuple[str, int, str], Path] = {}
    errors: dict[tuple[str, int, str], str] = {}
    hosts = (args.gateway_host,)
    for executor, wall_s in executor_walls:
        for task_id in task_ids:
            key = (executor, wall_s, task_id)
            target = _harbor_task_dir(args.work, executor, wall_s, task_id)
            staging: Path | None = None
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                staging = Path(tempfile.mkdtemp(dir=target.parent, prefix=f".{task_id}."))
                fresh = deps.to_harbor(
                    args.store / "visible" / task_id,
                    staging,
                    executor=executor,
                    allowed_hosts=hosts,
                    agent_timeout_sec=wall_s,
                )
                if (
                    target.is_dir()
                    and not target.is_symlink()
                    and tree_digest(target) == tree_digest(fresh)
                ):
                    converted[key] = target
                    continue
                if target.is_dir() and not target.is_symlink():
                    shutil.rmtree(target)
                elif target.exists() or target.is_symlink():
                    target.unlink()
                os.replace(fresh, target)
                converted[key] = target
            except Exception as exc:  # noqa: BLE001 - one bad task must not abort the matrix
                errors[key] = f"{type(exc).__name__}: {exc}"
            finally:
                if staging is not None:
                    shutil.rmtree(staging, ignore_errors=True)
    return converted, errors


def _run_one(
    run: PlannedRun,
    task: Mapping[str, Any],
    args: argparse.Namespace,
    deps: Deps,
    client: KeyClient,
    semaphores: Mapping[str, threading.Semaphore],
    converted: Mapping[tuple[str, int, str], Path],
    conversion_errors: Mapping[tuple[str, int, str], str],
    stop: threading.Event,
) -> bool:
    if stop.is_set():
        return False
    semaphore = semaphores[run.arm.provider]
    holder: dict[str, Any] = {}
    key = (run.arm.executor, _wall_s(run.arm), run.task_id)
    with semaphore:
        if stop.is_set():
            return False
        try:
            if key in conversion_errors:
                raise RuntimeError(conversion_errors[key])
            if key not in converted:
                raise RuntimeError(f"harbor task for {run.task_id} was not converted")
            document = build_input_document(run, args.store, task)
            attempt = _Attempt(
                run=run,
                task=task,
                input_document=document,
                holder=holder,
            )
            _execute_attempt(attempt, args, deps, client)
        except (KeyPoolExhausted, ProviderRateLimit):
            raise
        except Exception as exc:  # noqa: BLE001 - every planned run gets a verdict
            reason = _redact(f"{type(exc).__name__}: {exc}", holder.get("key"))
            _record_infra(run, args, deps, task, reason)
        return True


def _check_command(root: Path) -> int:
    runs = _load_directory(root / "runs")
    verdicts = _load_directory(root / "verdicts")

    run_ids = set(runs)
    valid_verdicts: dict[str, dict[str, Any]] = {}
    invalid_verdicts = 0
    for run_id, loaded in verdicts.items():
        document = loaded.document
        if document is None or not _is_verdict(document):
            invalid_verdicts += 1
            continue
        try:
            validate_document(document)
        except Exception:  # noqa: BLE001 - an invalid verdict is not a verdict
            invalid_verdicts += 1
            continue
        valid_verdicts[run_id] = document

    missing = sorted(run_ids - set(valid_verdicts))
    orphans = sorted(set(valid_verdicts) - run_ids)

    groups: dict[tuple[str, str, int], list[tuple[int, str, str]]] = {}
    for run_id, document in valid_verdicts.items():
        key = (document["arm"], document["task_id"], document["repetition"])
        groups.setdefault(key, []).append((document["attempt"], run_id, document["verdict"]))

    total_cells = len(groups)
    valid_outputs = 0
    infra = 0
    for entries in groups.values():
        _attempt, run_id, verdict = max(entries, key=lambda item: item[0])
        loaded = runs.get(run_id)
        valid = False
        if loaded is not None and loaded.document is not None:
            try:
                validate_run_document(loaded.document)
            except Exception:  # noqa: BLE001 - any invalid document counts as invalid
                valid = False
            else:
                valid = True
        if valid:
            valid_outputs += 1
        if verdict == ERROR_INFRA:
            infra += 1

    all_verdicts = not missing and not orphans and not invalid_verdicts
    enough_valid = total_cells > 0 and valid_outputs * 100 >= total_cells * 95
    few_infra = total_cells > 0 and infra * 100 <= total_cells * 5

    print(f"runs: {len(run_ids)}, verdicts: {len(run_ids) - len(missing)}/{len(run_ids)}")
    _print_ratio("valid outputs", valid_outputs, total_cells)
    _print_ratio("error_infra", infra, total_cells)
    if invalid_verdicts:
        print(f"invalid verdicts: {invalid_verdicts}")
    if orphans:
        print(f"verdicts without a run: {len(orphans)}")
    if missing:
        print(f"runs without a verdict: {len(missing)}")
    return 0 if all_verdicts and enough_valid and few_infra else 1


def _load_directory(directory: Path) -> dict[str, _Loaded]:
    loaded: dict[str, _Loaded] = {}
    if not directory.is_dir():
        return loaded
    for path in sorted(directory.glob("*.json")):
        loaded[path.stem] = _Loaded(document=_read_json(path))
    return loaded


def _is_verdict(document: Mapping[str, Any]) -> bool:
    attempt = document.get("attempt")
    repetition = document.get("repetition")
    return (
        isinstance(document.get("arm"), str)
        and isinstance(document.get("task_id"), str)
        and isinstance(attempt, int)
        and not isinstance(attempt, bool)
        and isinstance(repetition, int)
        and not isinstance(repetition, bool)
        and document.get("verdict") in VERDICTS
    )


def _print_ratio(label: str, numerator: int, denominator: int) -> None:
    percent = (numerator / denominator * 100.0) if denominator else 0.0
    print(f"{label}: {numerator}/{denominator} ({percent:.1f}%)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="factory.run_matrix", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="execute the matrix")
    run.add_argument("--store", type=Path, required=True)
    run.add_argument("--arms", type=Path, required=True)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--work", type=Path, required=True)
    run.add_argument("--arm", action="append", default=[])
    run.add_argument("--task", action="append", default=[])
    run.add_argument("--k", type=int)
    run.add_argument("--dry-run", action="store_true")
    run.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="public task manifest (default: tasks/public-v1.manifest.json)",
    )
    run.add_argument(
        "--keys-file",
        type=Path,
        default=os.environ.get("FACTORY_KEYS_FILE"),
        help="pre-minted virtual keys, one per line (default: $FACTORY_KEYS_FILE)",
    )
    run.add_argument(
        "--key-budget-usd",
        type=float,
        default=DEFAULT_KEY_BUDGET_USD,
        help="per-key budget fixed when the pool was minted (default: 2.0)",
    )
    run.add_argument(
        "--gateway-url",
        default=os.environ.get("FACTORY_GATEWAY_URL"),
        help="gateway base URL (default: $FACTORY_GATEWAY_URL)",
    )

    check = subparsers.add_parser("check", help="enforce the F0-18 gate")
    check.add_argument("root", type=Path)
    return parser


def main(argv: Sequence[str] | None = None, *, deps: Deps | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["--check"]:
        arguments = ["check", *arguments[1:]]
    args = build_parser().parse_args(arguments)
    deps = deps or Deps()

    if args.command == "run":
        if args.k is not None and args.k < 1:
            print("--k must be >= 1", file=sys.stderr)
            return 2
        gateway_url = args.gateway_url or os.environ.get("FACTORY_GATEWAY_URL")
        if not gateway_url:
            if not args.dry_run:
                print(
                    "--gateway-url or FACTORY_GATEWAY_URL is required for run",
                    file=sys.stderr,
                )
                return 2
            gateway_url = GATEWAY_BASE_URL
        try:
            host = urlsplit(gateway_url).hostname
        except ValueError:
            host = None
        if not host:
            print(f"invalid --gateway-url: {gateway_url!r}", file=sys.stderr)
            return 2
        args.gateway_url = gateway_url
        args.gateway_host = host
        for name in ("store", "arms", "out", "work", "manifest"):
            setattr(args, name, getattr(args, name).resolve())
        if args.keys_file is not None:
            args.keys_file = args.keys_file.resolve()
        return _run_command(args, deps)
    return _check_command(args.root.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
