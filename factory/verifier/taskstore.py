"""Load a task from the verifier's store (layout of ADR-0005)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema

SCHEMAS = Path(__file__).resolve().parents[2] / "schemas"
TASK_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,80}$")
MAX_OVERLAY_FILES = 200
MAX_FILE_BYTES = 2 * 1024 * 1024
# 3 x the cap of the class (docs/05 section 4, item 1). C4 has no cap in the docs: unknown
# classes fail closed instead of getting a made-up number.
PATCH_LINE_CAPS = {"C1": 600, "C2": 900}


class TaskError(RuntimeError):
    """The task is missing or malformed in the store. It is an infrastructure problem."""


@dataclass(frozen=True)
class Task:
    task_id: str
    task_class: str
    commit: str
    image: str
    visible_command: str
    visible_ids: tuple[str, ...]
    framework: str
    test_command: str
    junit_path: str
    timeout_s: int
    forbidden_globs: tuple[str, ...]
    f2p: tuple[str, ...]
    p2p: tuple[str, ...]
    known_failures: tuple[str, ...]
    test_patch: bytes
    verifier_bytes: bytes
    overlay: dict[str, bytes]
    spec_paths: frozenset[str]
    canary: bool = False

    @property
    def patch_line_cap(self) -> int:
        cap = PATCH_LINE_CAPS.get(self.task_class)
        if cap is None:
            raise TaskError(f"no patch size cap defined for class {self.task_class}")
        return cap


def _load_json(path: Path, schema_name: str | None) -> Any:
    try:
        document = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise TaskError(f"cannot read {path.name}: {exc}") from exc
    if schema_name:
        schema = json.loads((SCHEMAS / schema_name).read_text(encoding="utf-8"))
        try:
            jsonschema.Draft202012Validator(schema).validate(document)
        except jsonschema.ValidationError as exc:
            raise TaskError(f"{path.name} does not match {schema_name}: {exc.message}") from exc
    return document


def _id_list(path: Path) -> tuple[str, ...]:
    document = _load_json(path, None)
    if not isinstance(document, list) or not all(isinstance(item, str) for item in document):
        raise TaskError(f"{path.name} must be a list of strings")
    if len(set(document)) != len(document):
        raise TaskError(f"{path.name} repeats an id")
    return tuple(document)


SNAPSHOT_DIR = "snapshot"


def _read_tree(root: Path, skip: tuple[str, ...] = ()) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if path.relative_to(root).parts[0] in skip:
            continue
        if path.is_symlink():
            raise TaskError(f"symlink in the task store: {path}")
        if path.is_file():
            if len(files) >= MAX_OVERLAY_FILES or path.stat().st_size > MAX_FILE_BYTES:
                raise TaskError("visible task directory is too large")
            files[path.relative_to(root).as_posix()] = path.read_bytes()
    return files


def load_task(store: Path, task_id: str) -> Task:
    if not TASK_ID.match(task_id):
        raise TaskError("invalid task id")
    store = Path(store)
    visible_dir = store / "visible" / task_id
    hidden_dir = store / "hidden" / task_id
    for directory in (visible_dir, hidden_dir):
        if directory.is_symlink() or not directory.is_dir():
            raise TaskError(f"missing task directory: {directory.parent.name}/{task_id}")

    visible = _load_json(visible_dir / "factory.task.json", "task.schema.json")
    verifier = _load_json(hidden_dir / "verifier.json", "verifier-task.schema.json")
    verifier_bytes = (hidden_dir / "verifier.json").read_bytes()
    if visible["task_id"] != task_id or verifier["task_id"] != task_id:
        raise TaskError("task id in the documents does not match the directory")

    f2p = _id_list(hidden_dir / "f2p.json")
    p2p = _id_list(hidden_dir / "p2p.json")
    known_path = hidden_dir / "known_failures.json"
    known_failures = _id_list(known_path) if known_path.is_file() else ()
    if not f2p:
        raise TaskError("f2p.json is empty")
    if set(f2p) & set(p2p):
        raise TaskError("an id is in both f2p.json and p2p.json")
    try:
        test_patch = (hidden_dir / "test.patch").read_bytes()
    except OSError as exc:
        raise TaskError(f"cannot read test.patch: {exc}") from exc
    if not test_patch.strip():
        raise TaskError("test.patch is empty")

    tree = _read_tree(visible_dir, skip=(SNAPSHOT_DIR,))
    spec_paths = frozenset(path for path in tree if path != "factory.task.json")
    overlay = {
        path: data
        for path, data in tree.items()
        if path != "factory.task.json" and not path.startswith("openspec/")
    }
    return Task(
        task_id=task_id,
        task_class=visible["class"],
        commit=visible["repo"]["commit"],
        image=visible["image"],
        visible_command=visible["visible_tests"]["command"],
        visible_ids=tuple(visible["visible_tests"]["ids"]),
        framework=verifier["framework"],
        test_command=verifier["test_command"],
        junit_path=verifier["junit_path"],
        timeout_s=verifier["timeout_sec"],
        forbidden_globs=tuple(verifier["diff_guard"]["forbidden_globs"]),
        f2p=f2p,
        p2p=p2p,
        known_failures=known_failures,
        test_patch=test_patch,
        verifier_bytes=verifier_bytes,
        overlay=overlay,
        spec_paths=spec_paths,
        canary=verifier.get("canary", False),
    )
