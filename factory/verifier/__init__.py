"""Verifier v0: decides whether a candidate diff is accepted (docs/05)."""

from factory.verifier.engine import verify
from factory.verifier.sandbox import DockerSandbox, RunRequest, RunResult, Sandbox, SandboxError
from factory.verifier.verdict import Verdict, write_verdict

__all__ = [
    "DockerSandbox",
    "RunRequest",
    "RunResult",
    "Sandbox",
    "SandboxError",
    "Verdict",
    "verify",
    "write_verdict",
]
