"""Test id normalization shared by the miner and the verifier.

Pytest reports module paths with dots in JUnit (``tests.test_calc::test_x``) while
``f2p.json`` and ``p2p.json`` use node ids (``tests/test_calc.py::test_x``).
"""

from __future__ import annotations

from pathlib import Path


def pytest_node_id(test_id: str, repo_dir: Path) -> str:
    """Turn pytest's dotted classname into a pytest node id when it maps to a file."""
    prefix, separator, rest = test_id.partition("::")
    repo_dir = Path(repo_dir)
    if (repo_dir / prefix).is_file():
        return test_id
    parts = prefix.split(".")
    for index in range(len(parts), 0, -1):
        candidate = repo_dir.joinpath(*parts[:index]).with_suffix(".py")
        if candidate.is_file():
            tail = parts[index:] + ([rest] if separator else [])
            relative = candidate.relative_to(repo_dir).as_posix()
            return "::".join([relative, *tail])
    return test_id
