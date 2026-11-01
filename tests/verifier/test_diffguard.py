"""Unit tests for the diff-guard rules and the glob translator."""

from __future__ import annotations

import pytest

from factory.verifier.diffguard import (
    RULES,
    Change,
    GuardConfig,
    compile_glob,
    evaluate,
    is_test_path,
    matches_any_glob,
    rule_ids,
)


def change(
    path: str, status: str = "M", *, lines: tuple[str, ...] = (), **kwargs: object
) -> Change:
    modes = {"A": ("000000", "100644"), "D": ("100644", "000000")}.get(status, ("100644", "100644"))
    fields: dict[str, object] = {
        "path": path,
        "status": status,
        "old_mode": modes[0],
        "new_mode": modes[1],
        "added_lines": lines,
    }
    fields.update(kwargs)
    return Change(**fields)  # type: ignore[arg-type]


def ids(*changes: Change, **config: object) -> list[str]:
    return rule_ids(evaluate(list(changes), GuardConfig(**config)))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        (change("tests/test_calc.py"), "dg.test-modified"),
        (change("tests/test_calc.py", "D"), "dg.test-deleted"),
        (change("src/app.test.ts"), "dg.test-modified"),
        (change("src/a.py", lines=("@pytest.mark.skip",)), "dg.skip-marker"),
        (change("src/a.py", lines=("@pytest.mark.xfail(reason='x')",)), "dg.skip-marker"),
        (change("src/a.py", lines=("    pytest.skip('no')",)), "dg.skip-marker"),
        (change("src/a.py", lines=("@unittest.skip('x')",)), "dg.skip-marker"),
        (change("src/a.test.ts", "A", lines=("it.only('x', () => {})",)), "dg.skip-marker"),
        (change("src/a.test.ts", "A", lines=("xit('x', () => {})",)), "dg.skip-marker"),
        (change("conftest.py", "A"), "dg.python-startup-hook"),
        (change("pkg/sub/conftest.py", "A"), "dg.python-startup-hook"),
        (change("sitecustomize.py", "A"), "dg.python-startup-hook"),
        (change("usercustomize.py", "A"), "dg.python-startup-hook"),
        (change("evil.pth", "A"), "dg.python-startup-hook"),
        (change("pytest.ini", "A"), "dg.runner-config"),
        (change("tox.ini"), "dg.runner-config"),
        (change("pyproject.toml", lines=('addopts = "-k x"',)), "dg.runner-config"),
        (change("docs/notes.md", "A", lines=("addopts = -x",)), "dg.runner-config"),
        (change("jest.config.js"), "dg.runner-config"),
        (change("vitest.config.ts"), "dg.runner-config"),
        (change(".env", "A"), "dg.env-file"),
        (change(".env.local", "A"), "dg.env-file"),
        (change(".npmrc", "A"), "dg.env-file"),
        (change("link", "A", new_mode="120000"), "dg.symlink"),
        (change("sub", "A", new_mode="160000"), "dg.submodule"),
        (change("run.sh", old_mode="100644", new_mode="100755"), "dg.mode-change"),
        (change("blob.bin", "A", binary=True), "dg.binary-file"),
        (change(".gitattributes", "A"), "dg.git-metadata"),
        (change(".gitignore", "A"), "dg.git-metadata"),
        (change(".gitmodules", "A"), "dg.git-metadata"),
        (change(".github/workflows/ci.yml", "A"), "dg.ci-config"),
        (change("package-lock.json", "A"), "dg.lockfile"),
        (change("uv.lock"), "dg.lockfile"),
        (change("package.json"), "dg.dependency-manifest"),
        (change("setup.py"), "dg.dependency-manifest"),
        (change("requirements-dev.txt"), "dg.dependency-manifest"),
        (change("package.json", lines=('"postinstall": "node x.js"',)), "dg.npm-install-script"),
        (change("package.json", lines=('  "prepare": "husky"',)), "dg.npm-install-script"),
        (change("src/__pycache__/a.cpython-312.pyc", "A"), "dg.bytecode-cache"),
        (change("x.pyc", "A"), "dg.bytecode-cache"),
        (change(".pytest_cache/CACHEDIR.TAG", "A"), "dg.bytecode-cache"),
        (change("node_modules/x/index.js", "A"), "dg.bytecode-cache"),
        (change("openspec/changes/t/proposal.md", "A"), "dg.spec-file"),
        (change("scripts/run tests.sh", "A"), "dg.runner-script"),
        (change("a\x07b.py", "A"), "dg.unsafe-path"),
        (change("a\\b.py", "A"), "dg.unsafe-path"),
    ],
    ids=lambda value: value.path if isinstance(value, Change) else value,
)
def test_rule_fires(spec: Change, expected: str) -> None:
    assert expected in ids(spec)


@pytest.mark.parametrize(
    "spec",
    [
        change("src/calc/__init__.py", lines=("return Decimal(x)",)),
        change("src/calc/new_module.py", "A", lines=("def f(): ...",)),
        change("README.md", lines=("docs only",)),
        change("src/calc/__init__.py", lines=("model.fit(x)", "queryset.only('id')")),
        change("tests/test_new.py", "A", lines=("def test_x(): assert 1",)),
    ],
    ids=lambda value: value.path,
)
def test_clean_changes_stay_clean(spec: Change) -> None:
    assert ids(spec) == []


def test_new_test_files_are_allowed_unless_a_glob_forbids_them() -> None:
    new_test = change("tests/test_new.py", "A")
    assert ids(new_test) == []
    assert ids(new_test, forbidden_globs=["tests/**"]) == ["dg.forbidden-glob"]


def test_spec_paths_and_command_tokens_come_from_the_task() -> None:
    config = {
        "spec_paths": frozenset({"tests/test_round_canary.py"}),
        "runner_commands": ["python -m pytest -q tools/check.py::test_x --junitxml=/logs/x.xml"],
    }
    assert "dg.spec-file" in ids(change("tests/test_round_canary.py", "A"), **config)
    assert "dg.runner-script" in ids(change("tools/check.py"), **config)


def test_every_rule_id_is_documented_and_stable() -> None:
    assert all(rule.startswith("dg.") and rule == rule.lower() for rule in RULES)
    fired = set()
    for spec in [
        change("tests/test_calc.py"),
        change("x", "A", new_mode="120000"),
    ]:
        fired |= set(ids(spec))
    assert fired <= set(RULES)


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("tests/**", "tests/a/b.py", True),
        ("tests/**", "src/tests/a.py", False),
        ("conftest.py", "deep/er/conftest.py", True),
        ("*.pth", "a/b/x.pth", True),
        ("**/__pycache__/**", "src/calc/__pycache__/x.pyc", True),
        ("**/__pycache__/**", "__pycache__/x.pyc", True),
        ("scripts/**", "scripts/run tests.sh", True),
        ("scripts/**", "a/scripts/x", False),
        ("src/*.py", "src/a.py", True),
        ("src/*.py", "src/sub/a.py", False),
        ("Tests/**", "tests/a.py", True),
        ("docs/", "docs/a/b.md", True),
        ("file?.txt", "file1.txt", True),
        ("[ab].txt", "a.txt", True),
        ("[!ab].txt", "a.txt", False),
    ],
)
def test_glob_semantics(pattern: str, path: str, expected: bool) -> None:
    assert bool(compile_glob(pattern).match(path)) is expected


def test_blank_globs_match_nothing() -> None:
    assert not matches_any_glob("a.py", ["", "  "])


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("tests/x.py", True),
        ("pkg/__tests__/x.js", True),
        ("src/test_x.py", True),
        ("src/x_test.py", True),
        ("src/x.spec.ts", True),
        ("src/contest.py", False),
        ("src/testing_utils.py", False),
    ],
)
def test_test_path_detection(path: str, expected: bool) -> None:
    assert is_test_path(path) is expected
