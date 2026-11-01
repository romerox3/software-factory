"""Import public task datasets from Hugging Face into the factory task store.

Rows are pinned by dataset revision: the temporal cutoff discards anything old
enough to have leaked into a model's training data, the gold patch decides the
task class, and the visible part is written as an OpenSpec change while the
test patch, the gold patch and the F2P/P2P lists stay in ``hidden/``.
"""

from __future__ import annotations

import json
import random
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import jsonschema
from huggingface_hub import snapshot_download

Source = Literal["rebench", "multilang"]
Framework = Literal["pytest", "jest", "vitest"]
TaskClass = Literal["C1", "C2"]

REPO_ROOT = Path(__file__).resolve().parents[2]
TASK_SCHEMA_PATH = REPO_ROOT / "schemas" / "task.schema.json"
VERIFIER_SCHEMA_PATH = REPO_ROOT / "schemas" / "verifier-task.schema.json"

JUNIT_PATH = "/logs/verifier/junit.xml"
DEFAULT_VERIFIER_TIMEOUT_SEC = 600

REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
TASK_ID_PATTERN = re.compile(r"[^a-z0-9._-]")

_CLASS_LIMITS: tuple[tuple[TaskClass, int, int], ...] = (
    ("C1", 3, 200),
    ("C2", 5, 300),
)

_FRAMEWORKS: tuple[Framework, ...] = ("jest", "vitest")

_VERIFIER_COMMANDS: dict[Framework, str] = {
    "pytest": "python -m pytest -q --junitxml=/logs/verifier/junit.xml",
    "jest": "JEST_JUNIT_OUTPUT=/logs/verifier/junit.xml npx jest --ci --reporters=jest-junit",
    "vitest": "npx vitest run --reporter=junit --outputFile=/logs/verifier/junit.xml",
}

_FALLBACK_TEST_COMMANDS: dict[Framework, str] = {
    "pytest": "python -m pytest -q",
    "jest": "npx jest --ci",
    "vitest": "npx vitest run",
}

_DIFF_GIT_PATTERN = re.compile(r"^diff --git a/(?P<old>\S+) b/(?P<new>\S+)$", re.MULTILINE)
_DIFF_NEW_FILE_PATTERN = re.compile(r"^\+\+\+ b/(?P<new>\S+)$", re.MULTILINE)

_MANIFEST_TASK_KEYS = ("dataset", "revision", "instance_id", "task_id", "image", "digest")


@dataclass(frozen=True)
class Candidate:
    """A row that passed every filter and can be written as a task."""

    instance_id: str
    task_id: str
    task_class: TaskClass
    repo: str
    base_commit: str
    image: str
    digest: str
    gold_patch: str
    test_patch: str
    fail_to_pass: list[str]
    pass_to_pass: list[str]
    problem_statement: str
    interface: str
    visible_command: str
    verifier_command: str
    framework: Framework
    verifier_timeout_sec: int
    forbidden_globs: list[str]


@dataclass(frozen=True)
class Rejection:
    """A row that was discarded, with the reason reported to the operator."""

    instance_id: str
    reason: str


def load_rows(path: Path) -> list[dict[str, Any]]:
    """Read the rows of a ``.jsonl`` or ``.parquet`` dataset export."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows
    if suffix == ".parquet":
        from pyarrow import parquet

        return parquet.read_table(path).to_pylist()
    raise ValueError(f"unsupported dataset export: {path}")


def download_split(dataset: str, revision: str, split: str, dest: Path) -> Path:
    """Download ``split`` of ``dataset`` at the pinned ``revision`` into ``dest``.

    The revision must be a full commit sha: a branch or tag can move under the
    task set and break reproducibility.
    """
    if not REVISION_PATTERN.fullmatch(revision):
        raise ValueError(f"revision must be a 40-hex commit sha: {revision!r}")
    dest = Path(dest)
    snapshot_download(
        repo_id=dataset,
        repo_type="dataset",
        revision=revision,
        local_dir=str(dest),
        allow_patterns=[f"**/{split}/**", f"{split}/**"],
    )
    return dest


def select(
    rows: list[dict[str, Any]],
    *,
    source: Source,
    cutoff: datetime,
    digests: dict[str, str],
    excluded_path_regexes: list[str],
    seed: int,
    limit: int,
) -> tuple[list[Candidate], list[Rejection]]:
    """Split ``rows`` into eligible candidates and rejections.

    Eligible rows are sorted by ``instance_id`` and then sampled with
    ``random.Random(seed)`` so the same seed always yields the same tasks.
    """
    if limit < 0:
        raise ValueError(f"limit must not be negative: {limit}")
    cutoff_utc = _as_utc(cutoff)
    patterns = [re.compile(pattern) for pattern in excluded_path_regexes]

    candidates: list[Candidate] = []
    rejections: list[Rejection] = []
    for row in rows:
        outcome = _evaluate(
            row, source=source, cutoff=cutoff_utc, digests=digests, patterns=patterns
        )
        if isinstance(outcome, Rejection):
            rejections.append(outcome)
        else:
            candidates.append(outcome)

    eligible = sorted(candidates, key=lambda candidate: candidate.instance_id)
    chosen = random.Random(seed).sample(eligible, k=min(limit, len(eligible)))
    return sorted(chosen, key=lambda candidate: candidate.instance_id), rejections


def write_task(
    candidate: Candidate,
    store: Path,
    *,
    dataset: str,
    revision: str,
    budget: dict[str, Any],
) -> str:
    """Write the visible and hidden parts of ``candidate`` into ``store``."""
    task_id = candidate.task_id
    task = {
        "schema_version": "1",
        "task_id": task_id,
        "class": candidate.task_class,
        "data_class": "public",
        "repo": {"commit": candidate.base_commit},
        "image": candidate.image,
        "visible_tests": {"command": candidate.visible_command, "ids": []},
        "budget": dict(budget),
        "source": {
            "dataset": dataset,
            "revision": revision,
            "instance_id": candidate.instance_id,
        },
    }
    verifier = {
        "schema_version": "1",
        "task_id": task_id,
        "test_command": candidate.verifier_command,
        "framework": candidate.framework,
        "junit_path": JUNIT_PATH,
        "timeout_sec": candidate.verifier_timeout_sec,
        "diff_guard": {"forbidden_globs": candidate.forbidden_globs},
        "mutation": {"enabled": False},
    }
    _validate(task, TASK_SCHEMA_PATH, "factory.task.json")
    _validate(verifier, VERIFIER_SCHEMA_PATH, "verifier.json")

    store = Path(store)
    visible_dir = store / "visible" / task_id
    change_dir = visible_dir / "openspec" / "changes" / task_id
    hidden_dir = store / "hidden" / task_id

    _write_json(visible_dir / "factory.task.json", task)
    _write_text(change_dir / "proposal.md", _proposal(candidate))
    _write_text(hidden_dir / "test.patch", _with_newline(candidate.test_patch))
    _write_text(hidden_dir / "gold.patch", _with_newline(candidate.gold_patch))
    _write_json(hidden_dir / "f2p.json", candidate.fail_to_pass)
    _write_json(hidden_dir / "p2p.json", candidate.pass_to_pass)
    _write_json(hidden_dir / "verifier.json", verifier)
    return task_id


def update_manifest(path: Path, entries: Iterable[Mapping[str, Any]]) -> None:
    """Merge ``entries`` into the public task manifest at ``path``.

    Only the reproducibility keys are stored: patches and F2P/P2P lists never
    reach this repository.
    """
    path = Path(path)
    tasks: dict[tuple[str, str, str], dict[str, str]] = {}
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        for entry in existing.get("tasks", []):
            tasks[_manifest_key(entry)] = _manifest_entry(entry)
    for entry in entries:
        tasks[_manifest_key(entry)] = _manifest_entry(entry)

    ordered = [tasks[key] for key in sorted(tasks)]
    datasets = sorted({(task["dataset"], task["revision"]) for task in ordered})
    document = {
        "schema_version": "1",
        "datasets": [{"dataset": name, "revision": rev} for name, rev in datasets],
        "tasks": ordered,
    }
    _write_json(path, document)


def _manifest_key(entry: Mapping[str, Any]) -> tuple[str, str, str]:
    return str(entry["dataset"]), str(entry["revision"]), str(entry["instance_id"])


def _manifest_entry(entry: Mapping[str, Any]) -> dict[str, str]:
    return {key: str(entry[key]) for key in _MANIFEST_TASK_KEYS}


def _evaluate(
    row: Mapping[str, Any],
    *,
    source: Source,
    cutoff: datetime,
    digests: Mapping[str, str],
    patterns: list[re.Pattern[str]],
) -> Candidate | Rejection:
    instance_id = str(row["instance_id"])
    if _parse_timestamp(row["created_at"]) <= cutoff:
        return Rejection(instance_id, "before_cutoff")

    docker_image = str(row["docker_image"])
    digest = digests.get(docker_image)
    if digest is None:
        return Rejection(instance_id, "no_digest")

    gold_patch = str(row.get("patch") or "")
    if any(pattern.search(path) for path in _patch_files(gold_patch) for pattern in patterns):
        return Rejection(instance_id, "excluded_path")

    task_class = _classify(gold_patch)
    if task_class is None:
        return Rejection(instance_id, "too_large")

    fail_to_pass = _string_list(row.get("FAIL_TO_PASS"))
    if not fail_to_pass:
        return Rejection(instance_id, "no_f2p")

    framework = _framework(row, source)
    if framework is None:
        return Rejection(instance_id, "unknown_framework")

    test_patch = str(row.get("test_patch") or "")
    return Candidate(
        instance_id=instance_id,
        task_id=_task_id(instance_id),
        task_class=task_class,
        repo=str(row["repo"]),
        base_commit=str(row["base_commit"]),
        image=f"{_without_tag(docker_image)}@{digest}",
        digest=digest,
        gold_patch=gold_patch,
        test_patch=test_patch,
        fail_to_pass=fail_to_pass,
        pass_to_pass=_string_list(row.get("PASS_TO_PASS")),
        problem_statement=str(row.get("problem_statement") or ""),
        interface=_interface(row.get("interface")),
        visible_command=_visible_command(row, source, framework),
        verifier_command=_VERIFIER_COMMANDS[framework],
        framework=framework,
        verifier_timeout_sec=_verifier_timeout(row, source),
        forbidden_globs=sorted(set(_patch_files(test_patch))),
    )


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return _as_utc(value)
    text = str(value).strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    return _as_utc(datetime.fromisoformat(text))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _task_id(instance_id: str) -> str:
    return TASK_ID_PATTERN.sub("-", instance_id.lower())


def _without_tag(image: str) -> str:
    name = image.split("@", 1)[0]
    slash = name.rfind("/")
    tag = name.rfind(":")
    if tag > slash:
        name = name[:tag]
    return name


def _patch_files(patch: str) -> list[str]:
    files = [match.group("new") for match in _DIFF_GIT_PATTERN.finditer(patch)]
    if files:
        return files
    return [match.group("new") for match in _DIFF_NEW_FILE_PATTERN.finditer(patch)]


def _changed_lines(patch: str) -> int:
    changed = 0
    for line in patch.splitlines():
        if line.startswith(("+++", "---")):
            continue
        if line.startswith(("+", "-")):
            changed += 1
    return changed


def _classify(patch: str) -> TaskClass | None:
    files = len(_patch_files(patch))
    changed = _changed_lines(patch)
    for task_class, max_files, max_lines in _CLASS_LIMITS:
        if files <= max_files and changed <= max_lines:
            return task_class
    return None


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            return [str(item) for item in json.loads(text)]
        return [text]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return [str(value)]


def _interface(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        return json.dumps(dict(value), indent=2, sort_keys=True)
    return str(value).strip()


def _framework(row: Mapping[str, Any], source: Source) -> Framework | None:
    if source == "rebench":
        return "pytest"
    log_parser = str(row.get("log_parser") or "").lower()
    from_parser = _single_framework(log_parser)
    if from_parser is not None:
        return from_parser
    commands = " ".join(_string_list(row.get("test_cmds"))).lower()
    return _single_framework(commands)


def _single_framework(text: str) -> Framework | None:
    named = [name for name in _FRAMEWORKS if name in text]
    return named[0] if len(named) == 1 else None


def _visible_command(row: Mapping[str, Any], source: Source, framework: Framework) -> str:
    if source == "multilang":
        commands = _string_list(row.get("test_cmds"))
        if commands:
            return " && ".join(commands)
    return _FALLBACK_TEST_COMMANDS[framework]


def _verifier_timeout(row: Mapping[str, Any], source: Source) -> int:
    raw = row.get("harbor_verifier_timeout_sec") if source == "rebench" else None
    if raw is None:
        return DEFAULT_VERIFIER_TIMEOUT_SEC
    return max(60, int(raw))


def _proposal(candidate: Candidate) -> str:
    parts = [candidate.problem_statement.strip()]
    if candidate.interface:
        parts.extend(["## Interface", candidate.interface])
    return _with_newline("\n\n".join(part for part in parts if part))


def _validate(document: dict[str, Any], schema_path: Path, name: str) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    try:
        jsonschema.Draft202012Validator(schema).validate(document)
    except jsonschema.ValidationError as exc:
        raise ValueError(f"{name} does not match the schema: {exc.message}") from exc


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, document: Any) -> None:
    _write_text(path, json.dumps(document, indent=2) + "\n")


def _with_newline(text: str) -> str:
    if not text or text.endswith("\n"):
        return text
    return f"{text}\n"
