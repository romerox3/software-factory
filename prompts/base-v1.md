# Base prompt v1

Solve the task described below inside the repository at `{{ workdir }}`.

{{ task }}

## Rules

- The existing tests and the test configuration files are **read-only**. You may
  run them, but changing them invalidates the submission.
- There is no network except the model endpoint.
- The repository has no useful git history: do not look for the fix in it.
- Work only inside `{{ workdir }}`. Leave a coherent change behind; do not commit.

## Abort channel

If the specification and the visible tests contradict each other, or the task
cannot be completed without violating the specification, write
`{{ workdir }}/.factory/abort.json` with this shape and stop:

```json
{"reason": "...", "spec_refs": ["..."], "test_refs": ["..."]}
```

`reason` is required. `spec_refs` and `test_refs` are optional lists. Aborting
with a reason is not penalised.

## Repository instruction files

`AGENTS.md` and `CLAUDE.md`, when present, are part of the task and must be
followed as they are.
