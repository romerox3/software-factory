"""Render the per-arm F0 metric report and check the F0 exit criteria.

``python -m factory.metrics.report --runs <dir> --gold <json> --out <prefix>``
writes ``<prefix>.md`` and ``<prefix>.json``. ``--check <file.md>`` verifies
that a report has a value for every F0 exit criterion.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from factory.metrics.core import BASELINE_ARM, DEFAULT_K, compute
from factory.metrics.load import load_dataset
from factory.metrics.stats import paired_bootstrap

BOOTSTRAP_N = 10000
BOOTSTRAP_SEED = 0
EXIT_CRITERIA: dict[str, tuple[str, ...]] = {
    "A": (
        "valid_tasks",
        "contract_valid_rate",
        "error_infra_rate",
        "verifier_reproducibility",
        "false_accepts",
        "reject_concordance",
        "best_arm_pass_at_1",
    ),
    # M4 needs the pilot repo, so it is a phase C criterion, not a phase A one.
    "C": ("m4_baseline",),
}
DEFAULT_PHASE = "A"


def build_report(
    runs_dir: Path,
    gold: Mapping[str, str],
    *,
    sources: Mapping[str, Path] | None = None,
    k: int = DEFAULT_K,
    n: int = BOOTSTRAP_N,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Compute the report payload for every arm and compare each with A1.

    ``sources`` maps each task id to its base source tree; without it the M7a
    and M7b values stay ``None``.
    """
    dataset = load_dataset(runs_dir)
    metrics = compute(dataset, k=k, gold=gold, sources=sources)

    arms = {
        arm: {
            "pass_at_1": value.pass_at_1,
            "pass_pow_k": value.pass_pow_k,
            "m1_gen": value.m1_gen,
            "m1_total": value.m1_total,
            "m7a": value.m7a,
            "m7b": value.m7b,
            "m7c": value.m7c,
            "tasks": value.tasks,
            "error_infra": value.error_infra,
        }
        for arm, value in metrics.items()
    }

    bootstrap: dict[str, dict[str, float | None]] = {}
    baseline = metrics.get(BASELINE_ARM)
    if baseline is not None:
        for arm, value in metrics.items():
            if arm == BASELINE_ARM:
                continue
            diff, lo, hi = paired_bootstrap(value.per_task, baseline.per_task, n=n, seed=seed)
            bootstrap[arm] = {"diff": diff, "lo": lo, "hi": hi}

    return {
        "schema_version": "1",
        "k": k,
        "arms": arms,
        "bootstrap_vs_A1": bootstrap,
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    """Render the report as a Markdown table plus the paired comparisons."""
    k = report["k"]
    lines = [
        "# F0 metrics",
        "",
        (
            f"First {k} repetitions per task. Costs are USD; M7a is the complexity delta vs gold, "
            "M7b the new duplicate blocks vs gold, M7c the candidate/gold size."
        ),
        "",
        f"| Arm | pass@1 | pass^{k} | M1.gen | M1.total | M7a | M7b | M7c | Tasks | error_infra |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for arm, value in report["arms"].items():
        lines.append(
            "| "
            + " | ".join(
                (
                    arm,
                    _format_rate(value["pass_at_1"]),
                    _format_rate(value["pass_pow_k"]),
                    _format_usd(value["m1_gen"]),
                    _format_usd(value["m1_total"]),
                    _format_delta(value["m7a"]),
                    _format_delta(value["m7b"]),
                    _format_ratio(value["m7c"]),
                    str(value["tasks"]),
                    str(value["error_infra"]),
                )
            )
            + " |"
        )

    lines.extend(["", f"## Paired bootstrap of pass@1 vs {BASELINE_ARM}", ""])
    bootstrap = report["bootstrap_vs_A1"]
    if not bootstrap:
        lines.append(f"No arm besides {BASELINE_ARM}.")
    else:
        lines.extend(
            [
                "| Arm | diff | 95% CI low | 95% CI high |",
                "|---|---|---|---|",
            ]
        )
        for arm, value in bootstrap.items():
            lines.append(
                "| "
                + " | ".join(
                    (
                        arm,
                        _format_delta(value["diff"]),
                        _format_delta(value["lo"]),
                        _format_delta(value["hi"]),
                    )
                )
                + " |"
            )
    return "\n".join(lines) + "\n"


def write_report(prefix: str | Path, report: Mapping[str, Any]) -> tuple[Path, Path]:
    """Write ``<prefix>.md`` and ``<prefix>.json`` and return both paths."""
    base = Path(prefix)
    base.parent.mkdir(parents=True, exist_ok=True)
    markdown_path = Path(f"{base}.md")
    json_path = Path(f"{base}.json")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return markdown_path, json_path


def missing_criteria(text: str, phase: str = DEFAULT_PHASE) -> list[str]:
    """Return the exit criteria of ``phase`` without a valued line in ``text``."""
    return [
        key
        for key in EXIT_CRITERIA[phase]
        if not any(_line_has_value(line, key) for line in text.splitlines())
    ]


def _line_has_value(line: str, key: str) -> bool:
    match = re.search(rf"(?<![\w-]){re.escape(key)}(?![\w-])", line)
    if match is None:
        return False
    rest = line[match.end() :].lstrip(" \t|:=-\u2014")
    return re.search(r"\d", rest) is not None


def _load_gold(path: Path) -> dict[str, str]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON") from exc
    if not isinstance(document, dict):
        raise TypeError(f"{path}: expected an object mapping task_id to diff text")
    gold: dict[str, str] = {}
    for task_id, diff in document.items():
        if not isinstance(task_id, str) or not isinstance(diff, str):
            raise TypeError(f"{path}: task ids and diff texts must be strings")
        gold[task_id] = diff
    return gold


def _load_sources(path: Path) -> dict[str, Path]:
    if not path.is_dir():
        raise ValueError(f"{path}: not a directory")
    sources: dict[str, Path] = {}
    for task_dir in sorted(path.iterdir()):
        snapshot = task_dir / "snapshot"
        if task_dir.is_dir() and snapshot.is_dir():
            sources[task_dir.name] = snapshot
    return sources


def _format_rate(value: float | None) -> str:
    return f"{value:.2%}" if value is not None else "n/a"


def _format_usd(value: float | None) -> str:
    return f"${value:.4f}" if value is not None else "n/a"


def _format_ratio(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "n/a"


def _format_delta(value: float | None) -> str:
    return f"{value:+.4f}" if value is not None else "n/a"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report F0 metrics.")
    parser.add_argument("--runs", type=Path, help="directory with runs/ and verdicts/")
    parser.add_argument("--gold", type=Path, help="JSON object mapping task_id to gold diff")
    parser.add_argument("--out", help="output prefix; writes <prefix>.md and <prefix>.json")
    parser.add_argument(
        "--sources", type=Path, help="directory with <task_id>/snapshot base source trees"
    )
    parser.add_argument("--check", type=Path, help="Markdown report to check")
    parser.add_argument(
        "--phase", default=DEFAULT_PHASE, choices=sorted(EXIT_CRITERIA), help="phase to check"
    )
    args = parser.parse_args(argv)

    if args.out is None and args.check is None:
        parser.error("one of --out or --check is required")

    if args.out is not None:
        if args.runs is None or args.gold is None:
            parser.error("--out requires --runs and --gold")
        try:
            gold = _load_gold(args.gold)
            sources = _load_sources(args.sources) if args.sources is not None else None
            report = build_report(args.runs, gold, sources=sources)
            markdown_path, json_path = write_report(args.out, report)
        except (OSError, ValueError, TypeError) as exc:
            print(f"report: {exc}", file=sys.stderr)
            return 1
        print(f"wrote {markdown_path} and {json_path}")

    if args.check is not None:
        try:
            text = args.check.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"report: {exc}", file=sys.stderr)
            return 1
        missing = missing_criteria(text, args.phase)
        if missing:
            print(
                "missing exit criteria: " + ", ".join(missing),
                file=sys.stderr,
            )
            return 1
        print(f"{args.check}: all exit criteria present")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
