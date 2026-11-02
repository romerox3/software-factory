"""Pinned configuration for the four executor CLIs and their task images.

The versions and flags come from ``docs/04-executor-contract.md`` §5. Changing one
creates a new arm (repository rule 6), so the versions here are the only accepted
values for ``executor.version`` in an ``executor-input`` document.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

ExecutorName = Literal["claude-code", "codex", "opencode", "mini-swe-agent"]

GATEWAY_BASE_URL: Final = "http://gateway:4000/v1"

# The task images are Debian 12 without Node.js, and the task's own tools must
# keep precedence in ``PATH``: the Node runtime is copied under ``/opt`` and its
# bin directory is appended, never prepended.
NODE_IMAGE: Final = "node@sha256:4b150b48b4116e2a22f2c39cc27025fbf4f153e2078fd3b14d159fdb5c7279da"  # node:22-bookworm-slim

# ``uv`` installs mini-swe-agent into an isolated tool env so the task's Python
# environment (and its dependencies) is left untouched.
UV_IMAGE: Final = "ghcr.io/astral-sh/uv@sha256:f459f6f73a8c4ef5d69f4e6fbbdb8af751d6fa40ec34b39a1ab469acd6e289b7"  # uv:0.9.5

CLAUDE_CODE_IMAGE: Final = (
    f"COPY --from={NODE_IMAGE} /usr/local/ /opt/factory-node/",
    "ENV PATH=$PATH:/opt/factory-node/bin",
    "RUN npm install --global --prefix /opt/factory-node @anthropic-ai/claude-code@2.1.316 \\",
    " && claude --version",
)

# Codex writes a ``Cross-device link`` warning to stderr for ``--version``. Harbor
# parses that stderr as the version and reinstalls the CLI (spike 01, B3), so the
# pinned binary is hidden behind a wrapper that drops stderr for that one call.
CODEX_IMAGE: Final = (
    f"COPY --from={NODE_IMAGE} /usr/local/ /opt/factory-node/",
    "ENV PATH=$PATH:/opt/factory-node/bin",
    "RUN npm install --global --prefix /opt/factory-node @openai/codex@0.166.0 \\",
    ' && CODEX_BIN="$(command -v codex)" \\',
    ' && mv "$CODEX_BIN" "$CODEX_BIN.real" \\',
    " && printf '%s\\n' \\",
    "      '#!/bin/sh' \\",
    "      'case \"$1\" in' \\",
    '      "  --version|-V) exec \\"$CODEX_BIN.real\\" \\"\\$@\\" 2>/dev/null ;;" \\',
    "      'esac' \\",
    '      "exec \\"$CODEX_BIN.real\\" \\"\\$@\\"" \\',
    '      > "$CODEX_BIN" \\',
    ' && chmod 0755 "$CODEX_BIN" \\',
    " && codex --version",
)

OPENCODE_IMAGE: Final = (
    f"COPY --from={NODE_IMAGE} /usr/local/ /opt/factory-node/",
    "ENV PATH=$PATH:/opt/factory-node/bin",
    "RUN npm install --global --prefix /opt/factory-node opencode-ai@1.19.5 \\",
    " && opencode --version",
)

MINI_SWE_AGENT_IMAGE: Final = (
    f"COPY --from={UV_IMAGE} /uv /usr/local/bin/uv",
    "RUN UV_TOOL_DIR=/opt/factory-tools UV_TOOL_BIN_DIR=/opt/factory-tools/bin \\",
    "      UV_PYTHON_INSTALL_DIR=/opt/factory-tools/python \\",
    "      uv tool install --python 3.12 mini-swe-agent==2.4.6 \\",
    "      --with litellm --with orjson --with fastapi \\",
    " && /opt/factory-tools/bin/mini-swe-agent --help",
    "ENV PATH=$PATH:/opt/factory-tools/bin",
)


@dataclass(frozen=True)
class AgentConfig:
    """Everything that is fixed per executor, independent of one run."""

    name: ExecutorName
    harbor_agent: str
    cli_version: str
    model_prefix: str
    raw_format: str
    env_names: tuple[str, ...]
    image_lines: tuple[str, ...]


EXECUTORS: Final[dict[str, AgentConfig]] = {
    "claude-code": AgentConfig(
        name="claude-code",
        harbor_agent="factory_harbor_agents:PinnedClaudeCode",
        cli_version="2.1.316",
        model_prefix="anthropic/",
        raw_format="claude-stream-json",
        env_names=(
            "ANTHROPIC_BASE_URL",
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_DEFAULT_HAIKU_MODEL",
            "DISABLE_AUTOUPDATER",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
            "CLAUDE_CODE_ENABLE_TELEMETRY",
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "OTEL_RESOURCE_ATTRIBUTES",
        ),
        image_lines=CLAUDE_CODE_IMAGE,
    ),
    "codex": AgentConfig(
        name="codex",
        harbor_agent="factory_harbor_agents:PinnedCodex",
        cli_version="0.166.0",
        model_prefix="openai/",
        raw_format="codex-exec-jsonl",
        env_names=(
            "OPENAI_BASE_URL",
            "OPENAI_API_KEY",
            "FACTORY_GATEWAY_KEY",
        ),
        image_lines=CODEX_IMAGE,
    ),
    "opencode": AgentConfig(
        name="opencode",
        harbor_agent="factory_harbor_agents:PinnedOpenCode",
        cli_version="1.19.5",
        model_prefix="openai/",
        raw_format="opencode-run-json",
        env_names=(
            "OPENAI_BASE_URL",
            "OPENAI_API_KEY",
            "FACTORY_GATEWAY_KEY",
        ),
        image_lines=OPENCODE_IMAGE,
    ),
    "mini-swe-agent": AgentConfig(
        name="mini-swe-agent",
        harbor_agent="factory_harbor_agents:PinnedMiniSweAgent",
        cli_version="2.4.6",
        model_prefix="openai/",
        raw_format="mini-traj-json",
        env_names=(
            "OPENAI_BASE_URL",
            "OPENAI_API_BASE",
            "OPENAI_API_KEY",
            "MSWEA_API_KEY",
            "MSWEA_COST_TRACKING",
        ),
        image_lines=MINI_SWE_AGENT_IMAGE,
    ),
}


def agent_config(name: str) -> AgentConfig:
    """The pinned configuration for ``name``; unknown executors are rejected."""
    try:
        return EXECUTORS[name]
    except KeyError as exc:
        known = ", ".join(sorted(EXECUTORS))
        raise ValueError(f"unknown executor {name!r}; expected one of: {known}") from exc


def image_snippet(name: str) -> list[str]:
    """Dockerfile lines that bake the executor CLI into the task image, pinned."""
    return list(agent_config(name).image_lines)
