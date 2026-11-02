"""Build the ``harbor run`` command line for one ``executor-input`` document.

Only argument vectors are produced, never a shell string. Environment *names* are
returned separately: their values can be credentials, so they belong to the caller
and are never read, logged or printed here.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from factory.adapters.config import GATEWAY_BASE_URL, agent_config


@dataclass(frozen=True)
class HarborCommand:
    """``argv`` ready for ``subprocess`` plus the environment names the run needs."""

    argv: list[str]
    env_names: tuple[str, ...]
    model: str


def build_harbor_command(
    document: Mapping[str, Any],
    *,
    task_dir: str | Path,
    jobs_dir: str | Path,
    gateway_url: str = GATEWAY_BASE_URL,
    model_limits: Mapping[str, int] | None = None,
) -> HarborCommand:
    """Return the Harbor invocation for ``document`` (an ``executor-input``).

    ``model_limits`` carries the arm's context/output window when the executor
    needs it: OpenCode caps replies at 4096 tokens unless it knows the model, and
    Codex has no other way to learn the real window behind a gateway alias.
    """
    executor = document["executor"]
    config = agent_config(executor["name"])
    version = executor["version"]
    if version != config.cli_version:
        raise ValueError(
            f"{config.name} is pinned at {config.cli_version}, input asks for {version}"
        )

    alias = document["model"]["gateway_alias"]
    model = f"{config.model_prefix}{alias}"
    argv = [
        "harbor",
        "run",
        "--path",
        str(task_dir),
        "--agent",
        config.harbor_agent,
        "--model",
        model,
        "--jobs-dir",
        str(jobs_dir),
        "--job-name",
        document["run_id"],
    ]
    argv += _agent_kwargs(config.name, document, gateway_url, model_limits)
    return HarborCommand(argv=argv, env_names=config.env_names, model=model)


def _agent_kwargs(
    name: str,
    document: Mapping[str, Any],
    gateway_url: str = GATEWAY_BASE_URL,
    model_limits: Mapping[str, int] | None = None,
) -> list[str]:
    executor = document["executor"]
    budget = document["budget"]
    args = ["--agent-kwarg", f"version={executor['version']}"]

    if name == "claude-code":
        args += ["--agent-kwarg", "permission_mode=bypassPermissions"]
        # Claude Code prices the model with its own Anthropic rates, so its fuse
        # fires far too early behind a non-Anthropic alias; the gateway key's
        # budget is the authoritative one there.
        alias = document["model"]["gateway_alias"]
        if alias.startswith(("anthropic/", "claude-")):
            args += ["--agent-kwarg", f"max_budget_usd={budget['usd']}"]
        if "max_turns" in budget:
            args += ["--agent-kwarg", f"max_turns={budget['max_turns']}"]
        return args

    if name == "codex":
        # docs/04 §5.2: a native provider with the Responses bridge. Harbor
        # accepts an inline JSON object for ``config``.
        config = {
            "model_provider": "factory_gateway",
            "model_providers": {
                "factory_gateway": {
                    "name": "factory-gateway",
                    "base_url": gateway_url,
                    "env_key": "FACTORY_GATEWAY_KEY",
                    "wire_api": "responses",
                }
            },
        }
        if model_limits is not None:
            config["model_context_window"] = model_limits["context"]
            config["model_max_output_tokens"] = model_limits["output"]
        return args + ["--agent-kwarg", "config=" + json.dumps(config, separators=(",", ":"))]

    if name == "opencode":
        # docs/04 §5.3: OpenAI-compatible provider. Harbor resolves
        # ``openai/<alias>`` against the provider named ``openai``. The model id
        # OpenCode sees is the alias without that prefix.
        provider: dict[str, Any] = {
            "npm": "@ai-sdk/openai-compatible",
            "options": {
                "baseURL": gateway_url,
                "apiKey": "{env:FACTORY_GATEWAY_KEY}",
            },
        }
        if model_limits is not None:
            alias = document["model"]["gateway_alias"]
            provider["models"] = {
                alias: {
                    "limit": {
                        "context": model_limits["context"],
                        "output": model_limits["output"],
                    }
                }
            }
        config = {"provider": {"openai": provider}}
        return args + [
            "--agent-kwarg",
            "opencode_config=" + json.dumps(config, separators=(",", ":")),
        ]

    if name == "mini-swe-agent":
        # docs/04 §5.4: the CLI cost limit is a second fuse; the gateway key is
        # the authoritative one.
        return args + ["--agent-kwarg", f"cost_limit={budget['usd']}"]

    raise ValueError(f"unknown executor {name!r}")
