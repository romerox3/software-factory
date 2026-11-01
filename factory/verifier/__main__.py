"""Command line: ``python -m factory.verifier --task-store S --task-id ID --diff D --mirror M``.

Writes ``verdict.json`` into ``--out-dir`` (the verifier's own store) and, if asked, the
generator-facing ``feedback.json`` into ``--feedback-file``. Exit codes: 0 accept, 10 reject,
11 cheat_suspected, 20 error_infra, 2 bad usage. Anything but 0 is "not accepted".
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from factory.verifier.engine import verify
from factory.verifier.sandbox import DockerSandbox
from factory.verifier.verdict import Verdict, write_verdict

EXIT_CODES = {"accept": 0, "reject": 10, "cheat_suspected": 11, "error_infra": 20}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m factory.verifier", description=__doc__)
    parser.add_argument("--task-store", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument(
        "--diff", type=Path, required=True, help="diff.patch produced by the harness"
    )
    parser.add_argument("--mirror", type=Path, required=True, help="git mirror holding the base")
    parser.add_argument("--run", type=Path, help="executor output document (run.json)")
    parser.add_argument("--attempt", type=int, default=1)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--feedback-file", type=Path, help="write the generator-facing feedback")
    parser.add_argument("--run-id")
    parser.add_argument("--arm", default="unknown")
    parser.add_argument("--repetition", type=int, default=0)
    parser.add_argument("--base-commit", help="override the commit of factory.task.json")
    parser.add_argument("--image", help="override the task image (name@sha256:... or sha256:...)")
    parser.add_argument("--timeout-cap", type=int, help="upper bound for the test timeout, seconds")
    parser.add_argument("--sast-blocking", action="store_true", help="make the SAST stub block")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        sandbox = DockerSandbox(image=args.image, timeout_cap_s=args.timeout_cap)
        diff = args.diff.read_bytes()
        run: dict[str, Any] | None = None
        if args.run:
            run = json.loads(args.run.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"usage error: {exc}", file=sys.stderr)
        return 2
    verdict = verify(
        args.task_store,
        args.task_id,
        diff,
        args.mirror,
        run=run,
        sandbox=sandbox,
        attempt=args.attempt,
        run_id=args.run_id,
        arm=args.arm,
        repetition=args.repetition,
        base_commit=args.base_commit,
        sast_blocking=args.sast_blocking,
    )
    return _emit(verdict, args)


def _emit(verdict: Verdict, args: argparse.Namespace) -> int:
    try:
        write_verdict(verdict, args.out_dir)
        if args.feedback_file:
            args.feedback_file.parent.mkdir(parents=True, exist_ok=True)
            args.feedback_file.write_text(json.dumps(verdict.feedback) + "\n", encoding="utf-8")
    except Exception as exc:  # a verdict that cannot be stored must not look like an accept  # noqa: BLE001 - fail closed on purpose
        print(f"cannot write the verdict: {exc}", file=sys.stderr)
        return EXIT_CODES["error_infra"]
    print(f"{verdict.verdict}: {verdict.reason}")
    return EXIT_CODES[verdict.verdict]


if __name__ == "__main__":
    raise SystemExit(main())
