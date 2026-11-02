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


def test_codex_kwargs_use_the_given_gateway_url() -> None:
    command = build_harbor_command(
        _input("codex"),
        task_dir="t",
        jobs_dir="j",
        gateway_url="http://engine.example:9000/v1",
    )
    raw = next(value for value in command.argv if value.startswith("config="))
    config = json.loads(raw.split("=", 1)[1])
    provider = config["model_providers"]["factory_gateway"]
    assert provider["base_url"] == "http://engine.example:9000/v1"


def test_opencode_kwargs_use_the_given_gateway_url() -> None:
    command = build_harbor_command(
        _input("opencode"),
        task_dir="t",
        jobs_dir="j",
        gateway_url="http://engine.example:9000/v1",
    )
    raw = next(value for value in command.argv if value.startswith("opencode_config="))
    config = json.loads(raw.split("=", 1)[1])
    assert config["provider"]["openai"]["options"]["baseURL"] == "http://engine.example:9000/v1"


def test_opencode_model_limits_declare_the_alias_window() -> None:
    document = _input("opencode")
    alias = document["model"]["gateway_alias"]

    command = build_harbor_command(
        document,
        task_dir="t",
        jobs_dir="j",
        model_limits={"context": 200000, "output": 32768},
    )

    raw = next(value for value in command.argv if value.startswith("opencode_config="))
    config = json.loads(raw.split("=", 1)[1])
    assert config["provider"]["openai"]["models"] == {
        alias: {"limit": {"context": 200000, "output": 32768}}
    }


def test_opencode_without_model_limits_leaves_the_provider_unchanged() -> None:
    command = build_harbor_command(_input("opencode"), task_dir="t", jobs_dir="j")

    raw = next(value for value in command.argv if value.startswith("opencode_config="))
    config = json.loads(raw.split("=", 1)[1])
    assert "models" not in config["provider"]["openai"]


def test_codex_model_limits_carry_both_windows() -> None:
    command = build_harbor_command(
        _input("codex"),
        task_dir="t",
        jobs_dir="j",
        model_limits={"context": 32768, "output": 8192},
    )

    raw = next(value for value in command.argv if value.startswith("config="))
    config = json.loads(raw.split("=", 1)[1])
    assert config["model_context_window"] == 32768
    assert config["model_max_output_tokens"] == 8192


def test_executors_without_model_limits_keep_the_default_argv() -> None:
    for name in ("claude-code", "codex", "opencode", "mini-swe-agent"):
        document = _input(name)
        plain = build_harbor_command(document, task_dir="t", jobs_dir="j")
        explicit_none = build_harbor_command(
            document, task_dir="t", jobs_dir="j", model_limits=None
        )
        assert plain.argv == explicit_none.argv
        assert not any("model_context_window" in part for part in plain.argv)
        assert not any("model_max_output_tokens" in part for part in plain.argv)


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
    assert any(line.startswith("RUN ") for line in lines)


@pytest.mark.parametrize("name", sorted(EXECUTORS))
def test_image_snippet_leaves_the_task_environment_alone(name: str) -> None:
    lines = image_snippet(name)
    text = "\n".join(lines)
    assert "pip install" not in text
    for line in lines:
        if "npm install --global" in line:
            assert "--prefix /opt/factory-node" in line
        if line.startswith("ENV PATH="):
            assert "=$PATH:" in line
        if "COPY --from=" in line:
            assert "@sha256:" in line


def test_codex_image_uses_the_version_wrapper() -> None:
    text = "\n".join(image_snippet("codex"))
    assert "@openai/codex@0.166.0" in text
    assert '.real"' in text
    assert "2>/dev/null" in text


def test_other_image_snippets_pin_the_released_package() -> None:
    assert "@anthropic-ai/claude-code@2.1.316" in "\n".join(image_snippet("claude-code"))
    assert "opencode-ai@1.19.5" in "\n".join(image_snippet("opencode"))
    assert "mini-swe-agent==2.4.6" in "\n".join(image_snippet("mini-swe-agent"))


def test_every_harbor_agent_is_a_pinned_import_path() -> None:
    expected = {
        "claude-code": "PinnedClaudeCode",
        "codex": "PinnedCodex",
        "opencode": "PinnedOpenCode",
        "mini-swe-agent": "PinnedMiniSweAgent",
    }
    for name, class_name in expected.items():
        assert EXECUTORS[name].harbor_agent == f"factory_harbor_agents:{class_name}"


def test_mini_swe_agent_image_has_the_runtime_extras() -> None:
    text = "\n".join(image_snippet("mini-swe-agent"))
    assert "--with litellm --with orjson --with fastapi" in text
    assert "pip install" not in text


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
