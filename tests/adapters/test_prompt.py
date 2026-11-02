"""The base prompt template is rendered per task and never leaks a fixed path."""

from __future__ import annotations

import pytest

from factory.adapters import prompt as prompt_module
from factory.adapters.prompt import PROMPT_PATH, prompt_sha, prompt_text, render_prompt


def test_template_has_no_literal_workspace() -> None:
    assert "/workspace" not in prompt_text()


def test_render_prompt_substitutes_task_and_workdir() -> None:
    rendered = render_prompt("TASK-BODY", "/testbed")

    assert "TASK-BODY" in rendered
    assert "`/testbed`" in rendered
    assert "/testbed/.factory/abort.json" in rendered
    assert "{{" not in rendered


def test_unknown_placeholder_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prompt_module, "prompt_text", lambda: "hello {{ nope }}")

    with pytest.raises(ValueError, match="nope"):
        render_prompt("task", "/workspace")


def test_prompt_sha_still_hashes_the_template_file() -> None:
    assert prompt_sha() == prompt_module.sha256_label(PROMPT_PATH.read_bytes())
