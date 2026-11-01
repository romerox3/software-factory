"""The result plugin, run for real in the test image: its stream must agree with pytest's JUnit."""

from __future__ import annotations

import secrets
import shutil
from pathlib import Path

import pytest

from factory.junit import parse_junit
from factory.testids import pytest_node_id
from factory.verifier import RunRequest, engine
from factory.verifier.stream import parse_stream

SUITE = """
import pytest


@pytest.fixture
def broken_setup():
    raise RuntimeError("setup")


@pytest.fixture
def broken_teardown():
    yield
    raise RuntimeError("teardown")


def test_pass():
    assert True


def test_fail():
    assert False


@pytest.mark.skip(reason="no")
def test_skipped():
    pass


def test_skipped_at_runtime():
    pytest.skip("later")


@pytest.mark.xfail(reason="known")
def test_xfail():
    assert False


@pytest.mark.xfail(reason="fixed already")
def test_xpass_not_strict():
    assert True


@pytest.mark.xfail(strict=True, reason="fixed already")
def test_xpass_strict():
    assert True


def test_setup_error(broken_setup):
    pass


def test_teardown_error(broken_teardown):
    pass


@pytest.mark.parametrize("a,b", [("x", 1), ("y [odd] ::id", 2)])
def test_param(a, b):
    assert b


class TestGroup:
    def test_in_class(self):
        assert 1 == 1
"""


def run_suite(sandbox, workspace: Path, logs: Path, tmp: Path, *extra: str):
    plugin = tmp / "plugin"
    plugin.mkdir()
    module = "fv_" + secrets.token_hex(8)
    shutil.copy(engine.PLUGIN_SOURCE, plugin / f"{module}.py")
    for path in (workspace, logs, plugin):
        path.chmod(0o777)
    request = RunRequest(
        image=sandbox.image or "",
        workspace=workspace,
        logs_dir=logs,
        command="python -m pytest -q tests --junitxml=/logs/verifier/r.xml " + " ".join(extra),
        timeout_s=60,
        env=(
            ("PYTHONPATH", engine.PLUGIN_MOUNT),
            ("PYTEST_ADDOPTS", f"-p {module} -p no:cacheprovider"),
        ),
        read_only_mounts=((plugin, engine.PLUGIN_MOUNT),),
    )
    return sandbox.run(request)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_mix.py").write_text(SUITE, encoding="utf-8")
    return root


def test_the_stream_matches_the_junit_report_status_by_status(sandbox, workspace, tmp_path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    result = run_suite(sandbox, workspace, logs, tmp_path)
    report = parse_stream(result.stdout, truncated=result.stdout_truncated)
    assert report.problem is None, report.detail
    assert report.exit_status == 1  # test_fail and the others really failed
    xml = {
        pytest_node_id(test_id, workspace): status
        for test_id, status in parse_junit(logs / "r.xml").items()
    }
    for test_id in [i for i in xml if "fv_tripwire_" in i]:
        assert xml.pop(test_id) == "failed"
    assert report.statuses == xml
    assert report.statuses["tests/test_mix.py::test_pass"] == "passed"
    assert report.statuses["tests/test_mix.py::test_fail"] == "failed"
    assert report.statuses["tests/test_mix.py::test_xpass_not_strict"] == "passed"
    assert report.statuses["tests/test_mix.py::test_xpass_strict"] == "failed"
    assert report.statuses["tests/test_mix.py::test_setup_error"] == "error"
    assert report.statuses["tests/test_mix.py::test_teardown_error"] == "error"
    assert report.statuses["tests/test_mix.py::test_skipped"] == "skipped"
    assert report.statuses["tests/test_mix.py::test_xfail"] == "skipped"
    assert report.statuses["tests/test_mix.py::TestGroup::test_in_class"] == "passed"
    assert report.statuses["tests/test_mix.py::test_param[y [odd] ::id-2]"] == "passed"


def test_a_clean_suite_ends_with_exit_zero_although_the_tripwire_fails(
    sandbox, workspace, tmp_path
) -> None:
    (workspace / "tests" / "test_mix.py").write_text(
        "def test_one():\n    assert True\n", encoding="utf-8"
    )
    logs = tmp_path / "logs"
    logs.mkdir()
    result = run_suite(sandbox, workspace, logs, tmp_path)
    report = parse_stream(result.stdout, truncated=result.stdout_truncated)
    assert result.exit_code == 0 and report.exit_status == 0
    assert report.problem is None and report.statuses == {"tests/test_mix.py::test_one": "passed"}
    assert b"tripwire" in result.stdout  # it did run, and it did fail, in the container


def test_one_real_failure_keeps_the_exit_code_non_zero(sandbox, workspace, tmp_path) -> None:
    (workspace / "tests" / "test_mix.py").write_text(
        "def test_one():\n    assert False\n", encoding="utf-8"
    )
    logs = tmp_path / "logs"
    logs.mkdir()
    result = run_suite(sandbox, workspace, logs, tmp_path)
    report = parse_stream(result.stdout, truncated=result.stdout_truncated)
    assert result.exit_code == 1 and report.exit_status == 1
    assert report.statuses == {"tests/test_mix.py::test_one": "failed"}


def test_prints_stay_in_pytests_capture_and_a_blind_write_to_the_stream_is_a_forgery(
    sandbox, workspace, tmp_path
) -> None:
    """Printing is harmless; writing framed lines to the saved fd (found by scanning) is detected."""
    (workspace / "tests" / "test_mix.py").write_text(
        "import os, sys\n"
        "def test_print():\n"
        "    print('FV:' + '0' * 32 + ':{}')\n"
        "    sys.__stdout__.write('\\nFV:' + '0' * 32 + ':{}\\n')\n"
        "    sys.__stdout__.flush()\n"
        "def test_blind_write():\n"
        "    for fd in range(3, 40):\n"
        "        try:\n"
        "            os.write(fd, b'\\nFV:' + b'0' * 32 + b':{}\\n')\n"
        "        except OSError:\n"
        "            pass\n",
        encoding="utf-8",
    )
    logs = tmp_path / "logs"
    logs.mkdir()
    result = run_suite(sandbox, workspace, logs, tmp_path, "-k test_print")
    report = parse_stream(result.stdout, truncated=result.stdout_truncated)
    assert report.problem is None, report.detail
    assert report.statuses == {"tests/test_mix.py::test_print": "passed"}

    logs2 = tmp_path / "logs2"
    logs2.mkdir()
    (tmp_path / "again").mkdir()
    result = run_suite(sandbox, workspace, logs2, tmp_path / "again", "-k test_blind")
    assert parse_stream(result.stdout, truncated=result.stdout_truncated).forged
