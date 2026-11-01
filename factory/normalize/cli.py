"""Command line entry point of the trajectory normalizer."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import jsonschema

from factory.normalize import FORMATS, Trajectory, normalize_text

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "trajectory-event.schema.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m factory.normalize",
        description="Normalize raw executor output into trajectory events.",
    )
    parser.add_argument("--format", required=True, choices=sorted(FORMATS))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("input", type=Path, help="raw trajectory file")
    parser.add_argument("-o", "--output", type=Path, required=True, help="output JSONL file")
    args = parser.parse_args(argv)

    try:
        text = args.input.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot read {args.input}: {exc}", file=sys.stderr)
        return 2
    try:
        trajectory = normalize_text(args.format, args.run_id, text)
    except (TypeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    failures = _schema_failures(trajectory)
    print(
        f"format={args.format} run_id={args.run_id} events={len(trajectory.events)} "
        f"unmapped={trajectory.unmapped} skipped_non_json={trajectory.skipped_non_json} "
        f"invalid={len(failures)}"
    )
    if failures:
        for seq, message in failures:
            print(f"invalid event seq={seq}: {message}", file=sys.stderr)
        return 1

    trajectory.write(args.output)
    return 0


def _schema_failures(trajectory: Trajectory) -> list[tuple[int, str]]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    failures = []
    for event in trajectory.events:
        for error in validator.iter_errors(event.to_dict()):
            failures.append((event.seq, error.message))
            break
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
