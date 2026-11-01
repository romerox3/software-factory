"""Diff-guard: path and content rules over the changes a candidate diff makes.

The guard works on the change set that git computed after applying the diff to a clean
checkout (``factory.verifier.gitops``), never on the text of the diff itself, so quoting
tricks, renames and odd headers cannot hide a path. Every rule has a stable id; the ids
(and only the ids) may be fed back to the generator (docs/05 principle 7).
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache

# id -> what it blocks. The ids are part of the feedback whitelist: never rename them.
RULES: dict[str, str] = {
    "dg.test-modified": "an existing test file is edited",
    "dg.test-deleted": "an existing test file is deleted",
    "dg.skip-marker": "skip, xfail or only markers are added",
    "dg.python-startup-hook": "conftest.py, sitecustomize.py, usercustomize.py or a .pth file",
    "dg.runner-config": "test runner configuration (addopts, ini files, jest or vitest config)",
    "dg.env-file": "environment or package-manager configuration files",
    "dg.symlink": "a symlink (mode 120000)",
    "dg.submodule": "a submodule or gitlink (mode 160000)",
    "dg.mode-change": "a file mode change",
    "dg.git-metadata": "git metadata files (.gitattributes, .gitignore, .git*)",
    "dg.ci-config": "CI configuration",
    "dg.lockfile": "a dependency lockfile",
    "dg.dependency-manifest": "a dependency manifest or build script",
    "dg.npm-install-script": "an npm lifecycle script",
    "dg.bytecode-cache": "bytecode or cache artifacts",
    "dg.binary-file": "a binary file",
    "dg.forbidden-glob": "a path matching forbidden_globs of the task",
    "dg.spec-file": "the task spec or other task material",
    "dg.runner-script": "a script that the test command can run",
    "dg.unsafe-path": "a path with control characters or backslashes",
}

_TEST_DIRS = frozenset({"tests", "test", "__tests__", "spec", "specs"})
_TEST_NAME = re.compile(
    r"^(?:test_.*\.py|.*_test\.py|.*\.(?:test|spec)\.(?:[cm]?[jt]sx?))$", re.IGNORECASE
)
_STARTUP_NAMES = frozenset({"conftest.py", "sitecustomize.py", "usercustomize.py"})
_RUNNER_CONFIG = re.compile(
    r"^(?:pytest\.ini|tox\.ini|setup\.cfg|pyproject\.toml|\.coveragerc|noxfile\.py"
    r"|(?:jest|vitest|babel|playwright)\.config\.[cm]?[jt]s(?:on)?|\.babelrc(?:\.json)?"
    r"|jest\.setup\.[cm]?[jt]s|vitest\.workspace\.[cm]?[jt]s)$",
    re.IGNORECASE,
)
_ENV_FILE = re.compile(
    r"^(?:\.env(?:\..*)?|\.envrc|\.npmrc|\.yarnrc(?:\.yml)?|pip\.conf|\.pypirc|\.nvmrc)$",
    re.IGNORECASE,
)
_LOCKFILES = frozenset(
    {
        "package-lock.json",
        "npm-shrinkwrap.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "bun.lock",
        "bun.lockb",
        "poetry.lock",
        "uv.lock",
        "pipfile.lock",
        "pdm.lock",
        "cargo.lock",
        "go.sum",
        "gemfile.lock",
        "composer.lock",
    }
)
_MANIFESTS = re.compile(
    r"^(?:package\.json|requirements.*\.txt|constraints.*\.txt|pipfile|setup\.py|setup\.cfg"
    r"|pyproject\.toml|cargo\.toml|build\.rs|go\.mod|gemfile|composer\.json|pom\.xml"
    r"|build\.gradle(?:\.kts)?|makefile|dockerfile)$",
    re.IGNORECASE,
)
_CACHE_COMPONENTS = frozenset(
    {
        "__pycache__",
        ".pytest_cache",
        "node_modules",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        ".hypothesis",
        ".cache",
        ".venv",
    }
)
_CACHE_SUFFIXES = (".pyc", ".pyo", ".pyd")
_CI_PREFIXES = (".github", ".circleci", ".buildkite", ".gitlab-ci.yml", "jenkinsfile")
_SPEC_PREFIXES = ("openspec", ".factory")
_SCRIPT_DIRS = frozenset({"scripts"})

_SKIP_MARKERS = re.compile(
    r"\bpytest\.mark\.(?:skip|skipif|xfail)\b"
    r"|\bpytest\.(?:skip|xfail|importorskip)\s*\("
    r"|\bunittest\.(?:skip|skipIf|skipUnless|expectedFailure)\b"
    r"|^\s*@(?:skip|skipIf|skipUnless|expectedFailure)\b"
    r"|\bSkipTest\b|\bself\.skipTest\s*\("
    r"|\b(?:it|test|describe|context|suite|bench)\.(?:skip|only|todo|failing|fails)\b"
    r"|(?<![\w.])(?:xit|xdescribe|xtest|fit|fdescribe|ftest)\s*\("
)
_RUNNER_CONFIG_LINE = re.compile(
    r"\baddopts\b|\btestPathIgnorePatterns\b|\bpytest_plugins\b|\bcollect_ignore(?:_glob)?\b"
    r"|\bnorecursedirs\b|\[tool\.pytest|\[pytest\]|\[tool:pytest\]|--deselect\b"
    r"|\bxfail_strict\b|\bmodulePathIgnorePatterns\b|\btestMatch\b|\btestRegex\b",
    re.IGNORECASE,
)
_NPM_SCRIPT = re.compile(
    r'"(?:pre|post)?(?:install|uninstall|prepare|publish|pack)"\s*:|"prepublishOnly"\s*:',
    re.IGNORECASE,
)
_CONTROL = re.compile(r"[\x00-\x1f\x7f\\]")


@dataclass(frozen=True)
class Change:
    """One path touched by the diff, as reported by git after applying it."""

    path: str
    status: str  # A, M, D or T
    old_mode: str
    new_mode: str
    binary: bool = False
    added_lines: tuple[str, ...] = ()
    added: int = 0
    deleted: int = 0


@dataclass(frozen=True)
class Finding:
    rule_id: str
    path: str


@dataclass(frozen=True)
class GuardConfig:
    forbidden_globs: Sequence[str] = ()
    spec_paths: frozenset[str] = frozenset()
    runner_commands: Sequence[str] = ()


@lru_cache(maxsize=256)
def compile_glob(pattern: str) -> re.Pattern[str]:
    """Translate a glob into an anchored, case-insensitive regex over posix paths.

    ``*`` and ``?`` stay within one path segment, ``**`` crosses segments, and a pattern
    with no slash matches the basename at any depth (like a ``.gitignore`` entry). Matching
    is case-insensitive on purpose: a broader match fails closed.
    """
    pattern = pattern.strip()
    unanchored = "/" not in pattern.rstrip("/")
    pattern = pattern.lstrip("/")
    if pattern.endswith("/"):
        pattern += "**"
    out: list[str] = []
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif char == "*":
            out.append("[^/]*")
            i += 1
        elif char == "?":
            out.append("[^/]")
            i += 1
        elif char == "[":
            end = pattern.find("]", i + 2)
            if end == -1:
                out.append(re.escape(char))
                i += 1
            else:
                body = pattern[i + 1 : end]
                if body.startswith("!"):
                    body = "^" + body[1:]
                out.append("[" + body.replace("\\", "\\\\") + "]")
                i = end + 1
        else:
            out.append(re.escape(char))
            i += 1
    prefix = "(?:.*/)?" if unanchored else ""
    return re.compile(prefix + "".join(out) + r"\Z", re.IGNORECASE | re.DOTALL)


def matches_any_glob(path: str, patterns: Iterable[str]) -> bool:
    return any(compile_glob(pattern).match(path) for pattern in patterns if pattern.strip())


def is_test_path(path: str) -> bool:
    parts = [part.casefold() for part in path.split("/")]
    return any(part in _TEST_DIRS for part in parts[:-1]) or bool(_TEST_NAME.match(parts[-1]))


def _command_tokens(commands: Iterable[str]) -> set[str]:
    tokens: set[str] = set()
    for command in commands:
        try:
            words = shlex.split(command)
        except ValueError:
            words = command.split()
        for word in words:
            if word.startswith("-"):
                word = word.partition("=")[2]
            word = word.partition("::")[0].lstrip("./")
            if word:
                tokens.add(word.casefold())
    return tokens


def evaluate(changes: Sequence[Change], config: GuardConfig) -> list[Finding]:
    """Return every rule hit for ``changes``; an empty list means the guard is clean."""
    runner_tokens = _command_tokens(config.runner_commands)
    spec_paths = {path.casefold() for path in config.spec_paths}
    findings: list[Finding] = []
    for change in changes:
        for rule_id in sorted(_rules_for(change, config, runner_tokens, spec_paths)):
            findings.append(Finding(rule_id, change.path))
    return findings


def rule_ids(findings: Iterable[Finding]) -> list[str]:
    return sorted({finding.rule_id for finding in findings})


def _rules_for(
    change: Change, config: GuardConfig, runner_tokens: set[str], spec_paths: set[str]
) -> set[str]:
    path = change.path
    folded = path.casefold()
    parts = folded.split("/")
    name = parts[-1]
    hits: set[str] = set()

    if _CONTROL.search(path) or path.startswith("/") or ".." in parts:
        hits.add("dg.unsafe-path")
    if "120000" in (change.old_mode, change.new_mode):
        hits.add("dg.symlink")
    if "160000" in (change.old_mode, change.new_mode):
        hits.add("dg.submodule")
    if (
        change.status == "M"
        and change.old_mode != change.new_mode
        and "120000" not in (change.old_mode, change.new_mode)
    ):
        hits.add("dg.mode-change")
    if change.status == "T":
        hits.add("dg.mode-change")
    if change.binary:
        hits.add("dg.binary-file")

    existed = change.status in {"M", "D", "T"}
    if is_test_path(path) and existed:
        hits.add("dg.test-deleted" if change.status == "D" else "dg.test-modified")

    if name in _STARTUP_NAMES or name.endswith(".pth"):
        hits.add("dg.python-startup-hook")
    if _RUNNER_CONFIG.match(name):
        hits.add("dg.runner-config")
    if _ENV_FILE.match(name):
        hits.add("dg.env-file")
    if any(part.startswith(".git") for part in parts):
        hits.add("dg.git-metadata")
    if parts[0] in _CI_PREFIXES or name in _CI_PREFIXES:
        hits.add("dg.ci-config")
    if name in _LOCKFILES:
        hits.add("dg.lockfile")
    if _MANIFESTS.match(name):
        hits.add("dg.dependency-manifest")
    if any(part in _CACHE_COMPONENTS for part in parts) or name.endswith(_CACHE_SUFFIXES):
        hits.add("dg.bytecode-cache")
    if parts[0] in _SPEC_PREFIXES or folded in spec_paths:
        hits.add("dg.spec-file")
    if parts[0] in _SCRIPT_DIRS or folded in runner_tokens:
        hits.add("dg.runner-script")
    if matches_any_glob(path, config.forbidden_globs):
        hits.add("dg.forbidden-glob")

    for line in change.added_lines:
        if _SKIP_MARKERS.search(line):
            hits.add("dg.skip-marker")
        if _RUNNER_CONFIG_LINE.search(line):
            hits.add("dg.runner-config")
        if name == "package.json" and _NPM_SCRIPT.search(line):
            hits.add("dg.npm-install-script")
    return hits
