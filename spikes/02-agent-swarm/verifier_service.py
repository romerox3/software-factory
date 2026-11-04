"""Spike-only HTTP front for the factory verifier, run on the tower host.

Agent Swarm's ``script`` node runs inside the API container without Docker, so it
cannot start the verifier itself. It POSTs ``{"run_id", "task_id"}`` here instead.
The service takes the worker's directory, turns it into a diff against the snapshot
base, and hands only those bytes to ``python -m factory.verifier`` (rule 3). It
listens on the gateway IP of the compose ``verifier`` network, which only the API
container joins, so the worker cannot reach it.

Usage (from the factory checkout, with its venv):
    python spikes/02-agent-swarm/verifier_service.py --store S --work W --out O
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,160}$")
VERIFIER_TIMEOUT_S = 280


def diff_of(workdir: Path, base: str) -> bytes:
    """Diff of everything in the worker's tree against the snapshot commit.

    Uses a throwaway index and the base commit id from the verifier's own snapshot,
    so a worker that commits, resets or edits the index cannot hide changes.
    """
    with tempfile.TemporaryDirectory(prefix="spike-index-") as tmp:
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index"), "PATH": "/usr/bin:/bin"}
        git = ["git", "-C", str(workdir), "-c", "core.hooksPath=/dev/null", "-c", "safe.directory=*"]
        subprocess.run([*git, "read-tree", base], env=env, check=True, timeout=60)
        subprocess.run([*git, "add", "-A"], env=env, check=True, timeout=120)
        done = subprocess.run(
            [*git, "diff", "--cached", "--binary", base],
            env=env,
            check=True,
            capture_output=True,
            timeout=120,
        )
        return done.stdout


def ensure_image(task_file: Path) -> None:
    image = json.loads(task_file.read_text(encoding="utf-8"))["image"]
    present = subprocess.run(["docker", "image", "inspect", image], capture_output=True, timeout=60)
    if present.returncode != 0:
        subprocess.run(["docker", "pull", image], capture_output=True, check=True, timeout=1800)


def verify(store: Path, work: Path, out: Path, run_id: str, task_id: str) -> dict:
    workdir = work / run_id
    visible = store / "visible" / task_id
    run_out = out / run_id
    run_out.mkdir(parents=True, exist_ok=True)
    base = subprocess.run(
        ["git", "-C", str(visible / "snapshot"), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    ).stdout.strip()
    diff_path = run_out / "diff.patch"
    diff_path.write_bytes(diff_of(workdir, base))
    ensure_image(visible / "factory.task.json")
    argv = [
        sys.executable, "-m", "factory.verifier",
        "--task-store", str(store),
        "--task-id", task_id,
        "--diff", str(diff_path),
        "--mirror", str(visible / "snapshot"),
        "--base-commit", base,
        "--run-id", run_id,
        "--arm", "AS-spike",
        "--out-dir", str(run_out / "verifier"),
    ]  # fmt: skip
    done = subprocess.run(argv, capture_output=True, text=True, timeout=VERIFIER_TIMEOUT_S)
    verdict_file = run_out / "verifier" / "verdict.json"
    verdict = json.loads(verdict_file.read_text(encoding="utf-8")) if verdict_file.is_file() else {}
    return {
        "run_id": run_id,
        "task_id": task_id,
        "exit": done.returncode,
        "verdict": verdict.get("verdict", "error_infra"),
        "reason": verdict.get("reason"),
        "diff_bytes": diff_path.stat().st_size,
    }


def make_handler(store: Path, work: Path, out: Path) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - http.server naming
            if self.path != "/verify":
                self._send(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("content-length", "0"))
                body = json.loads(self.rfile.read(min(length, 4096)))
                run_id, task_id = body["run_id"], body["task_id"]
                if not (ID_RE.match(run_id) and ID_RE.match(task_id)):
                    raise ValueError("bad id")
            except (ValueError, KeyError, TypeError) as exc:
                self._send(400, {"error": str(exc)})
                return
            try:
                self._send(200, verify(store, work, out, run_id, task_id))
            except Exception as exc:  # noqa: BLE001 - report infra failures, never an accept
                self._send(500, {"verdict": "error_infra", "reason": f"{type(exc).__name__}: {exc}"})

        def _send(self, status: int, payload: dict) -> None:
            data = (json.dumps(payload) + "\n").encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--bind", default="172.31.241.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.bind, args.port), make_handler(args.store, args.work, args.out))
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
