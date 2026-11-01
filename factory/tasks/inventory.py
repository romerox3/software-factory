"""Report how many revalidated tasks a store holds, per language.

It is the gate F0-17 runs before freezing the public task set: a task only
counts when the revalidator (F0-10) wrote ``revalidation.json`` with
``"valid": true``, and the language comes from the hidden ``verifier.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

FRAMEWORK_LANGUAGES = {"pytest": "py", "jest": "ts", "vitest": "ts"}
UNKNOWN_LANGUAGE = "unknown"

Table = Counter[str]


def count_tasks(store: Path) -> tuple[Table, int]:
    """Return the valid tasks per language and the total number of valid tasks."""
    hidden = Path(store) / "hidden"
    counts: Table = Counter()
    total = 0
    if not hidden.is_dir():
        return counts, total
    for task_dir in sorted(path for path in hidden.iterdir() if path.is_dir()):
        if not _is_valid(task_dir / "revalidation.json"):
            continue
        total += 1
        counts[_language(task_dir / "verifier.json")] += 1
    return counts, total


def _is_valid(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return document.get("valid") is True


def _language(path: Path) -> str:
    if not path.is_file():
        return UNKNOWN_LANGUAGE
    try:
        framework = json.loads(path.read_text(encoding="utf-8")).get("framework")
    except (OSError, json.JSONDecodeError):
        return UNKNOWN_LANGUAGE
    return FRAMEWORK_LANGUAGES.get(str(framework), UNKNOWN_LANGUAGE)


def _parse_min_lang(value: str) -> tuple[str, int]:
    language, separator, count = value.partition("=")
    if not separator or not language or not count.isdigit():
        raise argparse.ArgumentTypeError(f"expected LANGUAGE=COUNT, got {value!r}")
    return language, int(count)


def _print_table(counts: Table, total: int, minimums: dict[str, int], min_valid: int) -> None:
    rows = [
        (language, counts.get(language, 0), minimums.get(language, 0))
        for language in sorted(set(counts) | set(minimums))
    ]
    rows.append(("total", total, min_valid))
    width = max(len(language) for language, _, _ in rows)
    print(f"{'LANGUAGE':<{width}}  {'VALID':>5}  {'MIN':>5}")
    for language, valid, minimum in rows:
        print(f"{language:<{width}}  {valid:>5}  {minimum:>5}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="factory.tasks.inventory")
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--min-valid", type=int, required=True)
    parser.add_argument("--min-lang", type=_parse_min_lang, action="append", default=[])
    args = parser.parse_args(argv)

    counts, total = count_tasks(args.store)
    minimums = dict(args.min_lang)
    _print_table(counts, total, minimums, args.min_valid)

    enough = total >= args.min_valid
    enough = enough and all(
        counts.get(language, 0) >= minimum for language, minimum in minimums.items()
    )
    return 0 if enough else 1


if __name__ == "__main__":
    sys.exit(main())
