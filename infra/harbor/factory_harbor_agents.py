"""Harbor agents that never install over the network.

The task images already bake the pinned executor CLI into ``/opt`` and append its
bin directory to ``PATH``. Harbor's stock installers would reinstall the CLI from
npm/uv inside the sandbox, which either needs the network (and fails) or mutates
the task's environment. These subclasses only verify the baked version and fail
loudly when the image carries something else.

Harbor runs this module in its own environment, so it must import nothing from
the ``factory`` package.
"""

from __future__ import annotations

import re
from typing import Any

from harbor.agents.installed.claude_code import ClaudeCode
from harbor.agents.installed.codex import Codex
from harbor.agents.installed.mini_swe_agent import MiniSweAgent
from harbor.agents.installed.opencode import OpenCode
from harbor.environments.base import BaseEnvironment

_VERSION = re.compile(r"\d+\.\d+\.\d+")


async def _require_baked_version(
    agent: Any, environment: BaseEnvironment, cli: str, command: str
) -> None:
    """Return when the image has ``agent._version``; refuse to install otherwise."""
    result = await environment.exec(command=command)
    stdout = result.stdout or ""
    match = _VERSION.search(stdout)
    found = match.group(0) if match else stdout.strip()
    wanted = agent._version
    if result.return_code == 0 and found == wanted:
        return
    raise RuntimeError(
        f"{cli} {wanted} is not baked into the task image (found {found or 'no version'}); "
        "refusing to install over the network"
    )


class PinnedClaudeCode(ClaudeCode):
    async def install(self, environment: BaseEnvironment) -> None:
        await _require_baked_version(self, environment, "claude", "claude --version")


class PinnedCodex(Codex):
    async def install(self, environment: BaseEnvironment) -> None:
        await _require_baked_version(self, environment, "codex", "codex --version")


class PinnedOpenCode(OpenCode):
    async def install(self, environment: BaseEnvironment) -> None:
        await _require_baked_version(self, environment, "opencode", "opencode --version")


class PinnedMiniSweAgent(MiniSweAgent):
    async def install(self, environment: BaseEnvironment) -> None:
        # The help banner carries "version X.Y.Z"; it needs no network.
        await _require_baked_version(self, environment, "mini-swe-agent", "mini-swe-agent --help")
