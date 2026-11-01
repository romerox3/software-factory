"""Validate the executor contract schemas and the examples shipped with them."""

import copy
import json
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).parents[1]
SCHEMAS_DIR = REPO_ROOT / "schemas"
EXAMPLES_DIR = REPO_ROOT / "examples" / "executor"

SCHEMA_PATHS = sorted(SCHEMAS_DIR.glob("*.json"))
EXAMPLE_PATHS = sorted(EXAMPLES_DIR.glob("*.json"))
TRAJECTORY_PATH = EXAMPLES_DIR / "trajectory.example.jsonl"
TRAJECTORY_LINES = TRAJECTORY_PATH.read_text(encoding="utf-8").splitlines()

INPUT_SCHEMA_PATH = SCHEMAS_DIR / "executor-input.schema.json"
OUTPUT_SCHEMA_PATH = SCHEMAS_DIR / "executor-output.schema.json"
TRAJECTORY_SCHEMA_PATH = SCHEMAS_DIR / "trajectory-event.schema.json"

INPUT_EXAMPLE_PATH = EXAMPLES_DIR / "claude-code.input.json"
OUTPUT_EXAMPLE_PATH = EXAMPLES_DIR / "claude-code.output.json"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


INPUT_SCHEMA = load_json(INPUT_SCHEMA_PATH)
OUTPUT_SCHEMA = load_json(OUTPUT_SCHEMA_PATH)
TRAJECTORY_SCHEMA = load_json(TRAJECTORY_SCHEMA_PATH)


def assert_rejected(document: dict, schema: dict) -> None:
    validator = jsonschema.Draft202012Validator(schema)
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(document)


@pytest.mark.parametrize("path", SCHEMA_PATHS, ids=lambda p: p.name)
def test_schemas_are_valid(path: Path) -> None:
    jsonschema.Draft202012Validator.check_schema(load_json(path))


@pytest.mark.parametrize("path", EXAMPLE_PATHS, ids=lambda p: p.name)
def test_examples_match_their_schema(path: Path) -> None:
    schema = INPUT_SCHEMA if path.name.endswith(".input.json") else OUTPUT_SCHEMA
    jsonschema.Draft202012Validator(schema).validate(load_json(path))


@pytest.mark.parametrize(
    "line", TRAJECTORY_LINES, ids=[f"line-{n}" for n in range(1, len(TRAJECTORY_LINES) + 1)]
)
def test_trajectory_events_are_valid(line: str) -> None:
    document = json.loads(line)
    jsonschema.Draft202012Validator(TRAJECTORY_SCHEMA).validate(document)


def test_input_rejects_latest_version() -> None:
    document = copy.deepcopy(load_json(INPUT_EXAMPLE_PATH))
    document["executor"]["version"] = "latest"
    assert_rejected(document, INPUT_SCHEMA)


def test_input_rejects_caret_range_version() -> None:
    document = copy.deepcopy(load_json(INPUT_EXAMPLE_PATH))
    document["executor"]["version"] = "^2.1.0"
    assert_rejected(document, INPUT_SCHEMA)


def test_input_rejects_wildcard_version() -> None:
    document = copy.deepcopy(load_json(INPUT_EXAMPLE_PATH))
    document["executor"]["version"] = "2.x"
    assert_rejected(document, INPUT_SCHEMA)


def test_input_rejects_short_commit() -> None:
    document = copy.deepcopy(load_json(INPUT_EXAMPLE_PATH))
    document["repo"]["commit"] = document["repo"]["commit"][:7]
    assert_rejected(document, INPUT_SCHEMA)


def test_input_rejects_canary_class() -> None:
    document = copy.deepcopy(load_json(INPUT_EXAMPLE_PATH))
    document["task"]["class"] = "canary"
    assert_rejected(document, INPUT_SCHEMA)


def test_output_rejects_abort_without_reason() -> None:
    document = copy.deepcopy(load_json(OUTPUT_EXAMPLE_PATH))
    document["exit"] = "abort_spec_conflict"
    del document["abort"]
    assert_rejected(document, OUTPUT_SCHEMA)


def test_output_rejects_agent_cost_source() -> None:
    document = copy.deepcopy(load_json(OUTPUT_EXAMPLE_PATH))
    document["cost"]["source"] = "agent"
    assert_rejected(document, OUTPUT_SCHEMA)
