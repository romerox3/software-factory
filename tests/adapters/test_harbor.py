"""Harbor command lines, pinned versions and image snippets."""

from __future__ import annotations

import json

import pytest

from factory.adapters import EXECUTORS, build_harbor_command, image_snippet
from factory.adapters.prompt import PROMPT_PATH, prompt_sha, prompt_text

from .support import EXAMPLES, load_json

PREFIX = {
    "claude-code": "anthropic/",
    "codex": "openai/",
    "opencode": "openai/",
    "mini-swe-agent": "openai/",
}


def _input(name: str) -> dict:
    return load_json(EXAMPLES / f"{name}.input.json")


@pytest.mark.parametrize("name", sorted(EXECUTORS))
def test_build_command_line_for_example(name: str) -> None:
    document = _input(name)
    command = build_harbor_command(document, task_dir="/tasks/calc", jobs_dir="/jobs")

    assert isinstance(command.argv, list)
    assert command.argv[:2] == ["harbor", "run"]
    assert _flag(command.argv, "--path") == "/tasks/calc"
    assert _flag(command.argv, "--agent") == EXECUTORS[name].harbor_agent
    assert _flag(command.argv, "--jobs-dir") == "/jobs"
    assert _flag(command.argv, "--job-name") == document["run_id"]

    alias = document["model"]["gateway_alias"]
    assert command.model == PREFIX[name] + alias
    assert _flag(command.argv, "--model") == command.model
    assert f"version={EXECUTORS[name].cli_version}" in command.argv

    assert set(EXECUTORS[name].env_names) == set(command.env_names)
    assert all("=" not in name for name in command.env_names)


def test_claude_code_kwargs_carry_the_two_fuses() -> None:
    document = _input("claude-code")
    command = build_harbor_command(document, task_dir="t", jobs_dir="j")
    assert "permission_mode=bypassPermissions" in command.argv
    assert f"max_budget_usd={document['budget']['usd']}" in command.argv
    assert f"max_turns={document['budget']['max_turns']}" in command.argv


def test_codex_kwargs_define_the_gateway_provider() -> None:
    command = build_harbor_command(_input("codex"), task_dir="t", jobs_dir="j")
    raw = next(value for value in command.argv if value.startswith("config="))
    config = json.loads(raw.split("=", 1)[1])
    provider = config["model_providers"]["factory_gateway"]
    assert config["model_provider"] == "factory_gateway"
    assert provider["wire_api"] == "responses"
    assert provider["env_key"] == "FACTORY_GATEWAY_KEY"


def test_opencode_kwargs_define_an_openai_compatible_provider() -> None:
    command = build_harbor_command(_input("opencode"), task_dir="t", jobs_dir="j")
    raw = next(value for value in command.argv if value.startswith("opencode_config="))
    config = json.loads(raw.split("=", 1)[1])
    provider = config["provider"]["openai"]
    assert provider["npm"] == "@ai-sdk/openai-compatible"
    assert provider["options"]["apiKey"] == "{env:FACTORY_GATEWAY_KEY}"


def test_mini_swe_agent_kwargs_carry_the_cost_limit() -> None:
    document = _input("mini-swe-agent")
    command = build_harbor_command(document, task_dir="t", jobs_dir="j")
    assert f"cost_limit={document['budget']['usd']}" in command.argv


def test_command_never_contains_a_secret_value() -> None:
    for name in EXECUTORS:
        command = build_harbor_command(_input(name), task_dir="t", jobs_dir="j")
        assert not any(part.startswith("sk-") for part in command.argv)


def test_mismatched_cli_version_is_rejected() -> None:
    document = _input("codex")
    document["executor"]["version"] = "0.1.0"
    with pytest.raises(ValueError, match="pinned"):
        build_harbor_command(document, task_dir="t", jobs_dir="j")


@pytest.mark.parametrize("name", sorted(EXECUTORS))
def test_image_snippet_pins_the_cli_version(name: str) -> None:
    lines = image_snippet(name)
    text = "\n".join(lines)
    assert EXECUTORS[name].cli_version in text
    assert lines[0].startswith("RUN ")


def test_codex_image_uses_the_version_wrapper() -> None:
    text = "\n".join(image_snippet("codex"))
    assert "@openai/codex@0.166.0" in text
    assert '.real"' in text
    assert "2>/dev/null" in text


def test_other_image_snippets_pin_the_released_package() -> None:
    assert "@anthropic-ai/claude-code@2.1.316" in "\n".join(image_snippet("claude-code"))
    assert "opencode-ai@1.19.5" in "\n".join(image_snippet("opencode"))
    assert "mini-swe-agent==2.4.6" in "\n".join(image_snippet("mini-swe-agent"))


def test_prompt_is_the_common_base_and_records_its_own_hash() -> None:
    text = prompt_text()
    assert "/workspace/.factory/abort.json" in text
    assert "read-only" in text
    assert "no network" in text
    assert PROMPT_PATH.name == "base-v1.md"
    assert prompt_sha().startswith("sha256:")
    assert len(prompt_sha()) == len("sha256:") + 64


def _flag(argv: list[str], name: str) -> str | None:
    index = argv.index(name)
    return argv[index + 1]
