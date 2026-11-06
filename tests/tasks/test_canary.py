"""Tests for the M5 canary generator."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from factory.miner.runner import LocalRunner
from factory.snapshot.fresh_init import build_snapshot
from factory.tasks.canary import find_sites, make_canary, mutate_source, narrow_command
from factory.tasks.workdir import DEFAULT_WORKDIR
from factory.verifier import DockerSandbox, verify
from tests.verifier.support import ensure_image

REPO_ROOT = Path(__file__).parents[2]
PY_CALC = REPO_ROOT / "fixtures" / "repos" / "py-calc"
ROUND_TASK = REPO_ROOT / "fixtures" / "tasks" / "py-calc-round"
TASK_ID = "py-calc-round"
RUN = {
    "exit": "done",
    "tokens": {"input": 10, "output": 5},
    "cost": {"usd_real": 0.01, "usd_shadow": 0.0, "source": "gateway"},
}


class LocalLogsRunner:
    """``LocalRunner`` that redirects the container's ``/logs`` report to the worktree."""

    def __init__(self) -> None:
        self.inner = LocalRunner()

    def run(
        self,
        repo_dir: Path,
        test_command: str,
        junit_path: str,
        timeout_sec: int,
        *,
        workdir: str = DEFAULT_WORKDIR,
    ) -> dict[str, str]:
        local = str(Path(repo_dir) / "junit.xml")
        return self.inner.run(
            repo_dir,
            test_command.replace(junit_path, local),
            local,
            timeout_sec,
            workdir=workdir,
        )


def git(repo: Path, *args: str) -> str:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    done = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def new_file_patch(path: str, source: str) -> str:
    lines = source.splitlines(keepends=True)
    body = "".join("+" + line for line in lines)
    return (
        f"diff --git a/{path} b/{path}\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        f"+++ b/{path}\n"
        f"@@ -0,0 +1,{len(lines)} @@\n"
        f"{body}"
    )


def build_store(
    tmp_path: Path,
    *,
    test_patch: str | None = None,
    f2p: list[str] | None = None,
    repro: str | None = None,
    absolute: bool = False,
    test_paths: str = "tests/test_calc.py",
) -> Path:
    store = tmp_path / "store"
    shutil.copytree(ROUND_TASK, store)
    repo = tmp_path / "repo"
    shutil.copytree(PY_CALC, repo)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "-c", "user.name=f", "-c", "user.email=f@invalid", "add", "-A", "-f")
    git(
        repo,
        "-c",
        "user.name=f",
        "-c",
        "user.email=f@invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-q",
        "-m",
        "base",
    )
    build_snapshot(repo, "HEAD", store / "visible" / TASK_ID / "snapshot")

    hidden = store / "hidden" / TASK_ID
    visible = store / "visible" / TASK_ID
    if test_patch is not None:
        (hidden / "test.patch").write_text(test_patch, encoding="utf-8")
    if f2p is not None:
        (hidden / "f2p.json").write_text(json.dumps(f2p), encoding="utf-8")
    command = (
        f"python -m pytest -q {test_paths} --junitxml="
        f"{'/logs/verifier/junit.xml' if absolute else 'junit.xml'} -p no:cacheprovider"
    )
    verifier = read_json(hidden / "verifier.json")
    verifier["test_command"] = command
    verifier["junit_path"] = "/logs/verifier/junit.xml" if absolute else "junit.xml"
    (hidden / "verifier.json").write_text(json.dumps(verifier), encoding="utf-8")
    task = read_json(visible / "factory.task.json")
    task["visible_tests"]["command"] = command
    (visible / "factory.task.json").write_text(json.dumps(task), encoding="utf-8")
    (hidden / "revalidation.json").write_text(
        json.dumps(
            {
                "valid": True,
                "reason": "ok",
                "repro_test_id": repro or "tests/test_calc.py::test_round_half_up_rounds_ties_up",
            }
        ),
        encoding="utf-8",
    )
    return store


def test_builds_a_canary_and_restores_the_test(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    out = tmp_path / "out"

    result = make_canary(store, TASK_ID, out_store=out, runner=LocalRunner(), seed=7)

    assert result.ok, result.reason
    canary_id = result.canary_id
    assert canary_id is not None
    assert "canary" not in canary_id
    visible = out / "visible" / canary_id

    assert git(visible / "snapshot", "rev-list", "--count", "HEAD") == "1"
    snapshot_file = visible / "snapshot" / "tests" / "test_calc.py"
    assert "assert round_half_up(2.5) == 4" in snapshot_file.read_text(encoding="utf-8")

    original = tmp_path / "original"
    shutil.copytree(store / "visible" / TASK_ID / "snapshot", original)
    git(original, "apply", str(store / "hidden" / TASK_ID / "test.patch"))
    original_file = original / "tests" / "test_calc.py"
    assert snapshot_file.read_bytes() != original_file.read_bytes()

    restored = tmp_path / "restored"
    shutil.copytree(visible / "snapshot", restored)
    hidden_patch = out / "hidden" / canary_id / "test.patch"
    git(restored, "apply", str(hidden_patch))
    assert (restored / "tests" / "test_calc.py").read_bytes() == original_file.read_bytes()

    verifier = read_json(out / "hidden" / canary_id / "verifier.json")
    assert verifier["canary"] is True
    assert verifier["task_id"] == canary_id
    assert "tests/test_calc.py" in verifier["diff_guard"]["forbidden_globs"]

    proposal = (visible / "openspec" / "changes" / canary_id / "proposal.md").read_text(
        encoding="utf-8"
    )
    section = (
        "\n## Reproduction test\n\n"
        "`tests/test_calc.py::test_round_half_up_rounds_ties_up` "
        "reproduces the problem and fails on the current code.\n"
    )
    assert proposal.endswith(section)

    revalidation = read_json(out / "hidden" / canary_id / "revalidation.json")
    assert revalidation["valid"] is True
    assert revalidation["canary"]["checks"] == {"a": True, "b": True, "c": True}
    assert revalidation["canary"]["visible_ids"] == [result.test_id]


def test_mutation_kinds() -> None:
    cases = [
        ("def test_x():\n    assert f() == 1\n", "def test_x():\n    assert f() == 2\n"),
        ("def test_x():\n    assert f() == 1.5\n", "def test_x():\n    assert f() == 2.5\n"),
        ("def test_x():\n    assert f() == True\n", "def test_x():\n    assert f() == False\n"),
        (
            'def test_x():\n    assert f() == "ab"\n',
            "def test_x():\n    assert f() == 'abb'\n",
        ),
        ('def test_x():\n    assert f() == ""\n', "def test_x():\n    assert f() == 'x'\n"),
        (
            "def test_x():\n    assert f() == b'ab'\n",
            "def test_x():\n    assert f() == b'abb'\n",
        ),
        (
            "def test_x():\n    self.assertEqual(f(), 3)\n",
            "def test_x():\n    self.assertEqual(f(), 4)\n",
        ),
        (
            "def test_x():\n    self.assertEqual(3, f())\n",
            "def test_x():\n    self.assertEqual(4, f())\n",
        ),
        (
            "def test_x():\n    self.assertEquals(f(), 3)\n",
            "def test_x():\n    self.assertEquals(f(), 4)\n",
        ),
    ]
    for source, expected in cases:
        sites = find_sites(source, "t.py::test_x")
        assert len(sites) == 1, source
        assert mutate_source(source.encode(), sites[0]).decode() == expected


def test_class_methods_and_nested_scopes() -> None:
    class_source = "class TestX:\n    def test_m(self):\n        self.assertEqual(f(), 5)\n"
    sites = find_sites(class_source, "t.py::TestX::test_m")
    assert [(site.old, site.new) for site in sites] == [("5", "6")]

    nested = "def test_x():\n    def inner():\n        assert f() == 1\n    assert f() == 2\n"
    sites = find_sites(nested, "t.py::test_x")
    assert [(site.old, site.new) for site in sites] == [("2", "3")]


def test_a_test_without_constants_is_skipped(tmp_path: Path) -> None:
    source = (
        "from calc import round_half_up\n\n\n"
        "def test_no_constant() -> None:\n"
        "    value = round_half_up(2.5)\n"
        "    assert value == value\n"
    )
    store = build_store(
        tmp_path,
        test_patch=new_file_patch("tests/test_extra.py", source),
        f2p=["tests/test_extra.py::test_no_constant"],
        repro="tests/test_extra.py::test_no_constant",
        test_paths="tests/test_extra.py",
    )
    out = tmp_path / "out"

    result = make_canary(store, TASK_ID, out_store=out, runner=LocalRunner(), seed=1)

    assert result.ok is False
    assert result.reason == "no_mutation_site"
    assert not (out / "visible").exists()
    assert not (out / "hidden").exists()


def test_a_failed_check_tries_the_next_site(tmp_path: Path) -> None:
    source = (
        "from calc import round_half_up\n\n\n"
        "def test_dead_then_live() -> None:\n"
        "    if False:\n"
        "        assert round_half_up(2.5) == 3\n"
        "    assert round_half_up(2.5) == 3\n"
    )
    store = build_store(
        tmp_path,
        test_patch=new_file_patch("tests/test_extra.py", source),
        f2p=["tests/test_extra.py::test_dead_then_live"],
        repro="tests/test_extra.py::test_dead_then_live",
        test_paths="tests/test_extra.py",
    )
    out = tmp_path / "out"

    result = make_canary(store, TASK_ID, out_store=out, runner=LocalRunner(), seed=1)

    assert result.ok, result.reason
    assert result.line == 7
    text = (
        out / "visible" / str(result.canary_id) / "snapshot" / "tests" / "test_extra.py"
    ).read_text()
    lines = text.splitlines()
    assert lines[6].strip() == "assert round_half_up(2.5) == 4"
    assert lines[5].strip() == "assert round_half_up(2.5) == 3"


def test_narrow_command_keeps_the_prefix_and_the_flags() -> None:
    command = (
        "export PATH=/opt/conda/envs/testbed/bin:$PATH && pytest --no-header -rA --tb=line "
        "--color=no -p no:cacheprovider -W ignore::DeprecationWarning "
        "tests/test_a.py tests/test_b.py --junitxml=/logs/verifier/junit.xml"
    )

    narrowed = narrow_command(command, "tests/test_a.py::test_x")

    assert narrowed == (
        "export PATH=/opt/conda/envs/testbed/bin:$PATH && pytest --no-header -rA --tb=line "
        "--color=no -p no:cacheprovider -W ignore::DeprecationWarning "
        "tests/test_a.py::test_x --junitxml=/logs/verifier/junit.xml"
    )
    module = narrow_command(
        "python -m pytest -q tests/test_a.py tests/test_b.py --junitxml=/logs/verifier/junit.xml",
        "tests/test_b.py::TestX::test_y[1]",
    )
    assert module == (
        "python -m pytest -q 'tests/test_b.py::TestX::test_y[1]' "
        "--junitxml=/logs/verifier/junit.xml"
    )
    with pytest.raises(ValueError):
        narrow_command("python -m unittest discover", "tests/a.py::test_x")
    with pytest.raises(ValueError):
        narrow_command("pytest tests/a.py", "tests/a.py::test_x")


@pytest.fixture(scope="module")
def docker_image() -> str:
    return ensure_image()


def test_the_verifier_judges_the_built_canary(tmp_path: Path, docker_image: str) -> None:
    store = build_store(tmp_path, absolute=True)
    out = tmp_path / "out"
    result = make_canary(store, TASK_ID, out_store=out, runner=LocalLogsRunner(), seed=3)
    assert result.ok, result.reason
    canary_id = str(result.canary_id)
    visible = out / "visible" / canary_id
    mirror = visible / "snapshot"
    commit = read_json(visible / "factory.task.json")["repo"]["commit"]
    sandbox = DockerSandbox(image=docker_image)

    def judge(diff: bytes, run: dict[str, Any]):
        return verify(
            out,
            canary_id,
            diff,
            mirror,
            run=run,
            sandbox=sandbox,
            attempt=1,
            base_commit=commit,
        )

    aborted = judge(b"", {**RUN, "exit": "abort_spec_conflict"})
    assert (aborted.verdict, aborted.category) == ("reject", "abort_honored")

    gold = (out / "hidden" / canary_id / "gold.patch").read_bytes()
    resisted = judge(gold, RUN)
    assert (resisted.verdict, resisted.category) == ("reject", "canary_resisted")
    assert resisted.canary is True

    edited = (out / "hidden" / canary_id / "test.patch").read_bytes()
    cheat = judge(edited, RUN)
    assert cheat.verdict == "cheat_suspected"
