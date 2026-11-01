"""The container really is the box docs/05 principle 6 describes, and the probes stay quiet."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest

from factory.verifier import DockerSandbox, RunRequest, RunResult, verify
from factory.verifier.sandbox import SandboxError

from .support import TASKS, TRAPS, FakeSandbox, docker, load_json, report_path

SECRET_MARKERS = ("f2p", "test_round_half_up_rounds", "expected", "assert", "tests/test_calc")


@pytest.fixture
def box(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "ws"
    logs = tmp_path / "logs"
    workspace.mkdir()
    logs.mkdir()
    for path in (workspace, logs):
        path.chmod(0o777)
    return workspace, logs


def run_in_box(sandbox: DockerSandbox, box, command: str, image: str, timeout: int = 60):
    workspace, logs = box
    request = RunRequest(
        image=image, workspace=workspace, logs_dir=logs, command=command, timeout_s=timeout
    )
    return sandbox.run(request)


def test_docker_arguments_are_the_isolated_ones(sandbox, tmp_path) -> None:
    request = RunRequest("sha256:" + "a" * 64, tmp_path / "w", tmp_path / "l", "true", 10)
    args = sandbox.docker_args(request, "name")
    assert args[:3] == ["docker", "run", "--rm"]
    assert args[args.index("--network") + 1] == "none"
    assert "--read-only" in args
    assert args[args.index("--user") + 1] == "65534:65534"
    assert args[args.index("--cap-drop") + 1] == "ALL"
    mounts = [args[i + 1] for i, value in enumerate(args) if value == "-v"]
    assert len(mounts) == 2
    assert mounts[0].endswith(":/workspace:rw") and mounts[1].endswith(":/logs/verifier:rw")
    assert not any("TOKEN" in value or "KEY" in value for value in args)
    assert args[args.index("--log-driver") + 1] == "none"  # no unbounded copy of stdout on the host


def test_the_workspace_mounts_at_the_task_workdir(sandbox, tmp_path) -> None:
    request = RunRequest(
        "sha256:" + "a" * 64, tmp_path / "w", tmp_path / "l", "true", 10, workdir="/testbed"
    )
    args = sandbox.docker_args(request, "name")
    mounts = [args[i + 1] for i, value in enumerate(args) if value == "-v"]
    assert mounts[0] == f"{tmp_path / 'w'}:/testbed:rw"
    assert args[args.index("-w") + 1] == "/testbed"


def test_extra_mounts_are_read_only_and_pythonpath_extends_the_image_one(sandbox, tmp_path) -> None:
    request = RunRequest(
        "sha256:" + "a" * 64,
        tmp_path / "w",
        tmp_path / "l",
        "true",
        10,
        env=(("PYTHONPATH", "/opt/factory-verifier"), ("PYTEST_ADDOPTS", "-p x")),
        read_only_mounts=((tmp_path / "p", "/opt/factory-verifier"),),
    )
    args = sandbox.docker_args(request, "name", {"PYTHONPATH": "/srv/lib", "PATH": "/bin"})
    mounts = [args[i + 1] for i, value in enumerate(args) if value == "-v"]
    assert mounts[2] == f"{tmp_path / 'p'}:/opt/factory-verifier:ro"
    variables = [args[i + 1] for i, value in enumerate(args) if value == "-e"]
    assert "PYTHONPATH=/opt/factory-verifier:/srv/lib" in variables
    assert "PYTEST_ADDOPTS=-p x" in variables
    assert sum(item.startswith("PYTEST_ADDOPTS=") for item in variables) == 1


def test_the_plugin_mount_cannot_be_written_from_inside(sandbox, image, box, tmp_path) -> None:
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    (plugin / "x.py").write_text("", encoding="utf-8")
    plugin.chmod(0o755)
    workspace, logs = box
    command = "python -c \"open('/opt/factory-verifier/new', 'w')\" 2>&1; echo ec=$?; ls /opt/factory-verifier"
    request = RunRequest(
        image, workspace, logs, command, 60, read_only_mounts=((plugin, "/opt/factory-verifier"),)
    )
    result = sandbox.run(request)
    assert "Read-only file system" in result.stdout_tail and "ec=1" in result.stdout_tail
    assert "new" not in result.stdout_tail.split("ec=1")[-1]


def test_container_has_no_network_no_root_and_a_read_only_filesystem(sandbox, image, box) -> None:
    script = (
        "import os, socket, sys\n"
        "routes = open('/proc/net/route').read().splitlines()\n"
        "assert len(routes) == 1, routes  # header only: no route out\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 53), 2)\n"
        "    sys.exit('reached the internet')\n"
        "except OSError:\n"
        "    pass\n"
        "assert os.getuid() == 65534\n"
        "for target in ('/etc/x', '/usr/x', '/opt/x'):\n"
        "    try:\n"
        "        open(target, 'w')\n"
        "        sys.exit('wrote ' + target)\n"
        "    except OSError:\n"
        "        pass\n"
        "open('/workspace/ok', 'w').close()\n"
        "open('/logs/verifier/ok', 'w').close()\n"
        "open('/tmp/ok', 'w').close()\n"
    )
    box[0].joinpath("check.py").write_text(script, encoding="utf-8")
    result = run_in_box(sandbox, box, "python check.py", image)
    assert result.exit_code == 0, result.stderr_tail
    assert (box[0] / "ok").exists() and (box[1] / "ok").exists()


def test_host_environment_does_not_reach_the_container(sandbox, image, box, monkeypatch) -> None:
    monkeypatch.setenv("FACTORY_TEST_SECRET", "s3cr3t-value")
    result = run_in_box(sandbox, box, "env", image)
    assert "s3cr3t-value" not in result.stdout_tail + result.stderr_tail


def test_only_the_workspace_and_logs_are_visible(sandbox, image, box) -> None:
    result = run_in_box(sandbox, box, "ls /; ls /logs", image)
    listing = result.stdout_tail.split()
    assert "verifier" in listing
    for name in ("hidden", "holdout", "store", "mirror"):
        assert name not in listing


def test_leak_holdout_path_probe_finds_nothing_in_the_verifier_box(sandbox, image, box) -> None:
    """T17/T29: run the generator-side probe inside the verifier's own container."""
    shutil.copy(TRAPS / "leak-holdout-path" / "probe.sh", box[0] / "probe.sh")
    result = run_in_box(sandbox, box, "bash probe.sh", image)
    lines = result.stdout_tail.splitlines()
    # /logs/verifier is the one legitimate mount of the verifier's box (the generator has none).
    assert [line for line in lines if line.startswith("EXISTS")] == ["EXISTS /logs/verifier"]
    section = lines[lines.index("== hidden task files in reach ==") + 1 :]
    assert not [
        line for line in section if line.endswith(("test.patch", "f2p.json", "verifier.json"))
    ]


def test_a_command_cannot_forge_a_docker_failure_exit_code(sandbox, image, box) -> None:
    for code in (125, 126, 127):
        result = run_in_box(sandbox, box, f"exit {code}", image)
        assert result.exit_code == 1


def test_a_hung_run_is_killed_and_reported_as_timeout(image, box) -> None:
    short = DockerSandbox(image=image, timeout_cap_s=3)
    result = run_in_box(short, box, "sleep 60", image, timeout=120)
    assert result.timed_out and result.exit_code is None
    for _ in range(20):  # the daemon removes the killed container asynchronously
        names = docker("ps", "-a", "--filter", "name=factory-verify-", "--format", "{{.Names}}")
        if not names.stdout.strip():
            break
        time.sleep(0.5)
    assert names.stdout.strip() == ""


def test_a_memory_hog_is_reported_as_oom(image, box) -> None:
    small = DockerSandbox(image=image, memory_mb=64)
    command = "python -c \"b = bytearray(600 * 1024 * 1024); b[::4096] = b'x' * len(b[::4096])\""
    result = run_in_box(small, box, command, image)
    assert result.oom_killed and result.exit_code == 137


def test_missing_image_is_a_sandbox_error(box) -> None:
    ghost = DockerSandbox(image="sha256:" + "f" * 64)
    with pytest.raises(SandboxError):
        run_in_box(ghost, box, "true", "sha256:" + "f" * 64)


def test_the_workspace_handed_to_the_container_holds_no_history_and_no_hidden_files(
    py_mirror,
) -> None:
    """T15/T17 on the verifier side: no .git, and the store never reaches the box."""
    seen: dict[str, object] = {}

    def behavior(request: RunRequest) -> RunResult:
        root = request.workspace
        seen["git"] = (root / ".git").exists()
        seen["names"] = {path.name for path in root.rglob("*")}
        seen["mounts"] = (root, request.logs_dir)
        report_path(request).write_text("<testsuites/>", encoding="utf-8")
        return RunResult(exit_code=0)

    gold = (TASKS / "py-calc-round" / "hidden" / "py-calc-round" / "gold.patch").read_bytes()
    verify(
        TASKS / "py-calc-round",
        "py-calc-round",
        gold,
        py_mirror[0],
        run=None,
        sandbox=FakeSandbox(behavior),
        attempt=1,
        base_commit=py_mirror[1],
    )
    assert seen["git"] is False
    assert not {"gold.patch", "f2p.json", "p2p.json", "verifier.json", "test.patch"} & seen["names"]  # type: ignore[operator]
    assert "test_calc.py" in seen["names"]  # type: ignore[operator]  # the hidden tests are in place


def test_feedback_leak_probe_reads_only_the_whitelisted_literal(
    sandbox, image, box, py_mirror
) -> None:
    """T28: feed the real retry feedback to the fixture's probe, as the second attempt would."""
    diff = b"""--- a/src/calc/__init__.py
+++ b/src/calc/__init__.py
@@ -1,3 +1,4 @@
+# harmless
 \"\"\"Tiny calculator used as a fixture repository.\"\"\"

 from __future__ import annotations
"""
    verdict = verify(
        TASKS / "py-calc-round",
        "py-calc-round",
        diff,
        py_mirror[0],
        run=None,
        sandbox=sandbox,
        attempt=2,
        base_commit=py_mirror[1],
    )
    assert verdict.verdict == "reject" and verdict.attempt == 2
    workspace, _ = box
    (workspace / ".factory-feedback.json").write_text(
        json.dumps(verdict.feedback), encoding="utf-8"
    )
    shutil.copy(TRAPS / "feedback-leak" / "probe.sh", workspace / "probe.sh")
    result = run_in_box(sandbox, box, "bash probe.sh", image)
    output = result.stdout_tail
    assert "fallan comprobaciones ocultas" in output
    assert output.strip().endswith("none")
    for marker in SECRET_MARKERS:
        assert marker not in output.lower()
    hidden_ids = load_json(TASKS / "py-calc-round" / "hidden" / "py-calc-round" / "f2p.json")
    assert not any(test_id in output for test_id in hidden_ids)


def test_the_real_feedback_of_a_diff_guard_hit_is_only_the_rule_id(py_mirror, sandbox) -> None:
    verdict = verify(
        TASKS / "py-calc-round",
        "py-calc-round",
        (TRAPS / "cheat-edit-test" / "patch.diff").read_bytes(),
        py_mirror[0],
        run=None,
        sandbox=sandbox,
        attempt=2,
        base_commit=py_mirror[1],
    )
    assert verdict.verdict == "reject"
    assert verdict.feedback == {
        "items": [
            {
                "type": "diff_guard",
                "rule_ids": ["dg.forbidden-glob", "dg.runner-script", "dg.test-modified"],
            }
        ]
    }
