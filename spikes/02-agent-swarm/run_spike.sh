#!/usr/bin/env bash
# Drives the spike on the tower: one workflow run per task and repetition.
# Usage: run_spike.sh <tasks-file> <repetitions>
# Each run gets a fresh copy of the task snapshot (no history, no hidden tests) in
# SPIKE_WORK_DIR, is triggered through the swarm API and is polled until it ends.
# Results go to $OUT/results.jsonl: the node path (criterion 1) and the verdict.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
# shellcheck disable=SC1091
. "$here/.env"
tasks_file=$1
reps=$2
STORE=${STORE:-$HOME/factory-f0/store}
CODE=${CODE:-$HOME/factory-f0/code}
OUT=${OUT:-$HOME/factory-f0/as-spike}
RUN_CAP_S=${RUN_CAP_S:-1500}
api=http://127.0.0.1:3013
auth=(-H "Authorization: Bearer $API_KEY" -H "content-type: application/json")
mkdir -p "$OUT" "$SPIKE_WORK_DIR"

wf_file=$OUT/workflow.id
if [ ! -s "$wf_file" ]; then
  body=$(sed "s/__WORKER_AGENT_ID__/$WORKER_AGENT_ID/" "$here/workflow.json" | python3 -I -c '
import json, sys
w = json.load(sys.stdin)
print(json.dumps({"name": w["name"], "description": w["description"],
                  "definition": {"nodes": w["nodes"]}, "triggerSchema": w["triggerSchema"]}))')
  curl -sS --fail-with-body "${auth[@]}" -X POST "$api/api/workflows" -d "$body" \
    | python3 -I -c 'import json,sys; d=json.load(sys.stdin); print(d.get("warnings") or "", file=sys.stderr); print(d["id"])' > "$wf_file"
fi
wf=$(cat "$wf_file")

while read -r task; do
  [ -n "$task" ] || continue
  for rep in $(seq 1 "$reps"); do
    run_id="as-${task}-r${rep}-$(date +%s)"
    cp -a "$STORE/visible/$task/snapshot" "$SPIKE_WORK_DIR/$run_id"
    chmod -R a+rwX "$SPIKE_WORK_DIR/$run_id"
    payload=$(cd "$CODE" && .venv/bin/python -I -c '
import json, sys
from pathlib import Path
from factory.tasks.to_harbor import _build_instruction
store, task, run_id = sys.argv[1:4]
print(json.dumps({"run_id": run_id, "task_id": task,
                  "statement": _build_instruction(Path(store) / "visible" / task, task)}))' \
      "$STORE" "$task" "$run_id")
    started=$(date +%s)
    swarm_run=$(curl -sS --fail-with-body "${auth[@]}" -X POST "$api/api/workflows/$wf/trigger?wait=false" -d "$payload" \
      | python3 -I -c 'import json,sys; print(json.load(sys.stdin)["runId"])')
    status=running
    while :; do
      curl -sS "${auth[@]}" "$api/api/workflow-runs/$swarm_run" > "$OUT/$run_id.run.json"
      status=$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["run"]["status"])' "$OUT/$run_id.run.json")
      case $status in completed|failed|cancelled|skipped) break ;; esac
      if [ $(( $(date +%s) - started )) -gt "$RUN_CAP_S" ]; then
        curl -sS "${auth[@]}" -X POST "$api/api/workflow-runs/$swarm_run/cancel" > /dev/null || true
        status=cap_exceeded
        break
      fi
      sleep 30
    done
    python3 -I - "$OUT/$run_id.run.json" "$run_id" "$task" "$status" "$started" >> "$OUT/results.jsonl" <<'EOF'
import json, sys, time
doc, run_id, task, status, started = sys.argv[1:6]
d = json.load(open(doc))
steps = sorted(d["steps"], key=lambda s: s.get("startedAt") or "")
verify = next((s for s in steps if s["nodeId"] == "verify"), {})
out = verify.get("output") or {}
print(json.dumps({
    "run_id": run_id, "task_id": task, "status": status,
    "path": [f'{s["nodeId"]}:{s["status"]}' for s in steps],
    "verdict": out.get("verdict"), "reason": out.get("reason"),
    "wall_s": int(time.time()) - int(started),
}))
EOF
    tail -1 "$OUT/results.jsonl"
  done
done < "$tasks_file"
