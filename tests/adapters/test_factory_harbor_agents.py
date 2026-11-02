"""The pinned Harbor agents only check the baked CLI; they never install it."""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "infra" / "harbor" / "factory_harbor_agents.py"

PARENTS = {
    "PinnedClaudeCode": "ClaudeCode",
    "PinnedCodex": "Codex",
    "PinnedOpenCode": "OpenCode",
    "PinnedMiniSweAgent": "MiniSweAgent",
}


def _tree() -> ast.Module:
    return ast.parse(MODULE_PATH.read_text(encoding="utf-8"))


def _classes() -> dict[str, ast.ClassDef]:
    return {node.name: node for node in _tree().body if isinstance(node, ast.ClassDef)}


def test_module_imports_nothing_from_factory() -> None:
    for node in ast.walk(_tree()):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert module != "factory" and not module.startswith("factory.")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "factory" and not alias.name.startswith("factory.")


def test_module_defines_the_four_pinned_agents() -> None:
    classes = _classes()
    for name, parent in PARENTS.items():
        assert name in classes
        assert [ast.unparse(base) for base in classes[name].bases] == [parent]
        installs = [
            item
            for item in classes[name].body
            if isinstance(item, ast.AsyncFunctionDef) and item.name == "install"
        ]
        assert len(installs) == 1


def test_no_install_calls_the_parent_installer() -> None:
    for node in _tree().body:
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if not isinstance(item, ast.AsyncFunctionDef) or item.name != "install":
                continue
            for call in ast.walk(item):
                if not (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "install"
                ):
                    continue
                parent = call.func.value
                assert not (
                    isinstance(parent, ast.Call)
                    and isinstance(parent.func, ast.Name)
                    and parent.func.id == "super"
                ), f"{node.name}.install calls super().install"


def test_the_classes_subclass_harbor_agents() -> None:
    pytest.importorskip("harbor")
    sys.path.insert(0, str(MODULE_PATH.parent))
    try:
        module = importlib.import_module("factory_harbor_agents")
    finally:
        sys.path.remove(str(MODULE_PATH.parent))

    from harbor.agents.installed.claude_code import ClaudeCode
    from harbor.agents.installed.codex import Codex
    from harbor.agents.installed.mini_swe_agent import MiniSweAgent
    from harbor.agents.installed.opencode import OpenCode

    for name, parent in (
        ("PinnedClaudeCode", ClaudeCode),
        ("PinnedCodex", Codex),
        ("PinnedOpenCode", OpenCode),
        ("PinnedMiniSweAgent", MiniSweAgent),
    ):
        assert issubclass(getattr(module, name), parent)
