"""Converting a visible task to Harbor must never leak the hidden part."""

import json
import os
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest

from factory.adapters import image_snippet
from factory.tasks.import_hf import REBENCH_ENV_PREFIX
from factory.tasks.to_harbor import to_harbor

DATA_DIR = Path(__file__).parent / "data"
VISIBLE_TASK_DIR = DATA_DIR / "visible" / "demo-task"
TASK = json.loads((VISIBLE_TASK_DIR / "factory.task.json").read_text(encoding="utf-8"))
GENERATED_FILES = [
    Path("environment") / "Dockerfile",
    Path("instruction.md"),
    Path("task.toml"),
    Path("tests") / "test.sh",
]


def copy_visible_task(tmp_path: Path) -> Path:
    task_dir = tmp_path / "visible" / "demo-task"
    shutil.copytree(VISIBLE_TASK_DIR, task_dir)
    return task_dir


def write_task_config(task_dir: Path, **overrides: Any) -> None:
    config = json.loads((task_dir / "factory.task.json").read_text(encoding="utf-8"))
    config.update(overrides)
    (task_dir / "factory.task.json").write_text(json.dumps(config), encoding="utf-8")


def test_conversion_copies_no_hidden_material(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"

    generated = to_harbor(copy_visible_task(tmp_path), out_dir)

    assert generated == out_dir / "demo-task"
    files = sorted(path.relative_to(generated) for path in generated.rglob("*") if path.is_file())
    assert files == GENERATED_FILES
    assert not (generated / "solution").exists()
    for path in generated.rglob("*"):
        assert "hidden" not in path.parts
        if path.is_file():
            assert "HIDDEN-MARKER-42" not in path.read_text(encoding="utf-8")


def test_instruction_joins_proposal_and_specs_in_order(tmp_path: Path) -> None:
    generated = to_harbor(copy_visible_task(tmp_path), tmp_path / "out")

    instruction = (generated / "instruction.md").read_text(encoding="utf-8")

    assert (
        instruction.index("PROPOSAL-CONTENT")
        < instruction.index("SPEC-ALPHA")
        < instruction.index("SPEC-BETA")
    )


def test_task_toml_and_dockerfile(tmp_path: Path) -> None:
    generated = to_harbor(copy_visible_task(tmp_path), tmp_path / "out")

    config = tomllib.loads((generated / "task.toml").read_text(encoding="utf-8"))
    assert config["schema_version"] == "1.4"
    assert config["agent"]["timeout_sec"] == TASK["budget"]["timeout_sec"]
    assert config["verifier"]["timeout_sec"] == 120.0
    assert config["environment"] == {"network_mode": "no-network", "cpus": 1, "memory_mb": 2048}

    dockerfile = (generated / "environment" / "Dockerfile").read_text(encoding="utf-8")
    assert dockerfile.splitlines()[0] == f"FROM {TASK['image']}"
    assert not any(line.startswith("ENV PATH=") for line in dockerfile.splitlines())

    test_script = generated / "tests" / "test.sh"
    contents = test_script.read_text(encoding="utf-8")
    assert contents.startswith("#!/usr/bin/env bash\nset -euo pipefail\n")
    assert TASK["visible_tests"]["command"] in contents
    assert os.access(test_script, os.X_OK)


def test_rebench_env_is_added_to_the_agent_image(tmp_path: Path) -> None:
    task_dir = copy_visible_task(tmp_path)
    write_task_config(
        task_dir,
        visible_tests={
            "command": f"{REBENCH_ENV_PREFIX}python -m pytest -q tests/visible",
            "ids": [],
        },
    )

    generated = to_harbor(task_dir, tmp_path / "out")

    dockerfile = (generated / "environment" / "Dockerfile").read_text(encoding="utf-8")
    assert dockerfile.splitlines()[-2:] == [
        "ENV PATH=/opt/conda/envs/testbed/bin:$PATH",
        "WORKDIR /workspace",
    ]
    test_script = (generated / "tests" / "test.sh").read_text(encoding="utf-8")
    assert f"{REBENCH_ENV_PREFIX}python -m pytest -q tests/visible" in test_script


def test_existing_task_directory_is_rejected(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    previous = out_dir / "demo-task" / "solution" / "solve.sh"
    previous.parent.mkdir(parents=True)
    previous.write_text("#!/usr/bin/env bash\necho old\n", encoding="utf-8")

    with pytest.raises(ValueError):
        to_harbor(copy_visible_task(tmp_path), out_dir)

    assert previous.read_text(encoding="utf-8") == "#!/usr/bin/env bash\necho old\n"
    assert sorted(
        path.relative_to(out_dir / "demo-task") for path in (out_dir / "demo-task").rglob("*")
    ) == [Path("solution"), Path("solution") / "solve.sh"]


def test_failure_while_writing_leaves_no_task_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_dir = tmp_path / "out"
    original_write_text = Path.write_text

    def failing_write_text(self: Path, data: str, *args: Any, **kwargs: Any) -> int:
        if self.name == "Dockerfile":
            raise OSError("disk full")
        return original_write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", failing_write_text)

    with pytest.raises(OSError):
        to_harbor(copy_visible_task(tmp_path), out_dir)

    assert not (out_dir / "demo-task").exists()
    assert list(out_dir.iterdir()) == []


@pytest.mark.parametrize("name", ["verifier.json", "test.patch"])
def test_hidden_file_inside_visible_task_is_rejected(tmp_path: Path, name: str) -> None:
    task_dir = copy_visible_task(tmp_path)
    (task_dir / name).write_text("HIDDEN-MARKER-42\n", encoding="utf-8")
    out_dir = tmp_path / "out"

    with pytest.raises(ValueError):
        to_harbor(task_dir, out_dir)

    assert not out_dir.exists()


def test_hidden_directory_inside_visible_task_is_rejected(tmp_path: Path) -> None:
    task_dir = copy_visible_task(tmp_path)
    (task_dir / "openspec" / "hidden").mkdir()
    out_dir = tmp_path / "out"

    with pytest.raises(ValueError):
        to_harbor(task_dir, out_dir)

    assert not out_dir.exists()


def test_symlink_inside_visible_task_is_rejected(tmp_path: Path) -> None:
    task_dir = copy_visible_task(tmp_path)
    (task_dir / "proposal-link.md").symlink_to(
        task_dir / "openspec" / "changes" / "demo-task" / "proposal.md"
    )
    out_dir = tmp_path / "out"

    with pytest.raises(ValueError):
        to_harbor(task_dir, out_dir)

    assert not out_dir.exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [("image", "python:3.12"), ("class", "canary")],
    ids=["image-without-digest", "canary-class"],
)
def test_invalid_task_is_rejected(tmp_path: Path, field: str, value: str) -> None:
    task_dir = copy_visible_task(tmp_path)
    write_task_config(task_dir, **{field: value})
    out_dir = tmp_path / "out"

    with pytest.raises(ValueError):
        to_harbor(task_dir, out_dir)

    assert not out_dir.exists()


def add_snapshot(task_dir: Path) -> Path:
    snapshot_git = task_dir / "snapshot" / ".git"
    snapshot_git.mkdir(parents=True)
    (snapshot_git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    return snapshot_git


def test_default_workdir_copies_the_snapshot_and_needs_no_checkout(tmp_path: Path) -> None:
    task_dir = copy_visible_task(tmp_path)
    add_snapshot(task_dir)

    generated = to_harbor(task_dir, tmp_path / "out")

    dockerfile = (generated / "environment" / "Dockerfile").read_text(encoding="utf-8")
    assert dockerfile == (
        f"FROM {TASK['image']}\n\nCOPY snapshot.git /workspace/.git\nWORKDIR /workspace\n"
    )
    assert (generated / "environment" / "snapshot.git" / "HEAD").is_file()


def test_real_workdir_checks_out_the_base_and_replaces_the_history(tmp_path: Path) -> None:
    task_dir = copy_visible_task(tmp_path)
    add_snapshot(task_dir)
    write_task_config(task_dir, repo={**TASK["repo"], "workdir": "/testbed"})

    generated = to_harbor(task_dir, tmp_path / "out")

    dockerfile = (generated / "environment" / "Dockerfile").read_text(encoding="utf-8")
    commit = TASK["repo"]["commit"]
    assert dockerfile == (
        f"FROM {TASK['image']}\n"
        "\n"
        f"RUN cd /testbed && git checkout -qf {commit} && rm -rf .git\n"
        "COPY snapshot.git /testbed/.git\n"
        "WORKDIR /testbed\n"
    )
    assert (generated / "environment" / "snapshot.git" / "HEAD").is_file()


def test_snapshot_contents_are_exempt_from_the_hidden_material_scan(tmp_path: Path) -> None:
    task_dir = copy_visible_task(tmp_path)
    add_snapshot(task_dir)
    snapshot = task_dir / "snapshot"
    (snapshot / "test.patch").write_text("a repo file named like ours\n", encoding="utf-8")
    (snapshot / "hidden").mkdir()
    (snapshot / "link").symlink_to(snapshot / ".git" / "HEAD")

    generated = to_harbor(task_dir, tmp_path / "out")

    assert (generated / "environment" / "snapshot.git" / "HEAD").is_file()


def test_real_workdir_without_snapshot_is_rejected(tmp_path: Path) -> None:
    task_dir = copy_visible_task(tmp_path)
    write_task_config(task_dir, repo={**TASK["repo"], "workdir": "/testbed"})

    with pytest.raises(ValueError, match="snapshot"):
        to_harbor(task_dir, tmp_path / "out")

    assert not (tmp_path / "out" / "demo-task").exists()


def git_snapshot(task_dir: Path) -> str:
    snapshot = task_dir / "snapshot"
    snapshot.mkdir()
    (snapshot / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(snapshot)], check=True)
    subprocess.run(["git", "-C", str(snapshot), "add", "-A"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(snapshot),
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "base",
        ],
        check=True,
    )
    completed = subprocess.run(
        ["git", "-C", str(snapshot), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def test_executor_lines_come_after_the_snapshot_and_before_workdir(tmp_path: Path) -> None:
    task_dir = copy_visible_task(tmp_path)
    add_snapshot(task_dir)

    generated = to_harbor(task_dir, tmp_path / "out", executor="codex")

    lines = (generated / "environment" / "Dockerfile").read_text(encoding="utf-8").splitlines()
    snippet = image_snippet("codex")
    start = lines.index(snippet[0])
    assert lines[start : start + len(snippet)] == snippet
    assert start > lines.index("COPY snapshot.git /workspace/.git")
    assert lines[start + len(snippet)] == "WORKDIR /workspace"


def test_no_executor_keeps_the_dockerfile_without_cli_lines(tmp_path: Path) -> None:
    task_dir = copy_visible_task(tmp_path)
    add_snapshot(task_dir)

    generated = to_harbor(task_dir, tmp_path / "out")

    dockerfile = (generated / "environment" / "Dockerfile").read_text(encoding="utf-8")
    assert "npm install" not in dockerfile


def test_allowed_hosts_switch_the_network_mode_to_an_allowlist(tmp_path: Path) -> None:
    generated = to_harbor(
        copy_visible_task(tmp_path),
        tmp_path / "out",
        allowed_hosts=("gateway.example.com", "api.example.com"),
    )

    config = tomllib.loads((generated / "task.toml").read_text(encoding="utf-8"))
    assert config["environment"] == {
        "network_mode": "allowlist",
        "allowed_hosts": ["gateway.example.com", "api.example.com"],
        "cpus": 1,
        "memory_mb": 2048,
    }


@pytest.mark.parametrize(
    "host",
    ["http://gateway", "gateway:4000", "bad host", "gate_way", ""],
    ids=["scheme", "port", "space", "underscore", "empty"],
)
def test_allowed_hosts_must_be_bare_hostnames(tmp_path: Path, host: str) -> None:
    out_dir = tmp_path / "out"

    with pytest.raises(ValueError, match="hostname"):
        to_harbor(copy_visible_task(tmp_path), out_dir, allowed_hosts=(host,))

    assert not out_dir.exists()


def test_test_script_exports_the_diff_against_the_snapshot_commit(tmp_path: Path) -> None:
    task_dir = copy_visible_task(tmp_path)
    commit = git_snapshot(task_dir)

    generated = to_harbor(task_dir, tmp_path / "out")

    script = (generated / "tests" / "test.sh").read_text(encoding="utf-8")
    assert (
        "cd /workspace && git add -A && "
        f"git diff --cached --binary {commit} > /logs/verifier/diff.patch"
    ) in script
    assert script.index("diff.patch") < script.index(TASK["visible_tests"]["command"])
    assert "echo 1 > /logs/verifier/reward.txt" in script


def test_test_script_uses_head_without_a_snapshot(tmp_path: Path) -> None:
    generated = to_harbor(copy_visible_task(tmp_path), tmp_path / "out")

    script = (generated / "tests" / "test.sh").read_text(encoding="utf-8")
    assert "git diff --cached --binary HEAD > /logs/verifier/diff.patch" in script
