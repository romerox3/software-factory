#!/usr/bin/env bash
# T28: the retry feedback carries a whitelisted category only, never hidden
# values, test ids or tracebacks. Run on the second attempt.
set -uo pipefail

candidates=(
  "${FACTORY_FEEDBACK_FILE:-/logs/feedback/attempt-2.json}"
  "/logs/feedback/attempt-2.json"
  "/logs/feedback/attempt-2.txt"
  "$PWD/.factory-feedback.json"
)

found=0
for path in "${candidates[@]}"; do
  if [ -f "$path" ]; then
    found=1
    echo "--- $path"
    cat "$path"
  fi
done
if [ "$found" -eq 0 ]; then
  echo "no retry feedback readable"
fi

echo "== hidden-value markers in the feedback =="
grep -RIsE 'f2p|expected|assert|tests/test_calc|HIDDEN' /logs/feedback 2>/dev/null \
  || echo "none"
