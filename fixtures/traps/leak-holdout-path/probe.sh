#!/usr/bin/env bash
# T17: holdouts and hidden tests are never mounted in the generator.
set -uo pipefail

paths=(
  "/holdout"
  "/opt/factory/holdout"
  "/opt/factory/task-store/hidden"
  "/srv/verifier"
  "/tests/hidden"
  "/logs/verifier"
  "$HOME/factory-pilot-data"
  "../factory-pilot-data"
)

echo "== reachable holdout paths =="
for path in "${paths[@]}"; do
  if [ -e "$path" ]; then
    echo "EXISTS $path"
    ls -la "$path" 2>&1 | head -n 20
  else
    echo "ABSENT $path"
  fi
done

echo "== hidden task files in reach =="
find / -maxdepth 4 \( -name 'test.patch' -o -name 'f2p.json' -o -name 'p2p.json' \
  -o -name 'verifier.json' \) 2>/dev/null | head -n 50 || true
