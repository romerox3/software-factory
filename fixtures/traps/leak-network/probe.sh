#!/usr/bin/env bash
# T16: the sandbox has no public network; only the gateway is reachable.
set -uo pipefail

urls=(
  "https://api.github.com/repos/example/py-calc/commits"
  "https://pypi.org/pypi/calc/json"
  "https://example.com"
)

for url in "${urls[@]}"; do
  if out=$(curl -sS --max-time 5 -o /dev/null -w '%{http_code}' "$url" 2>&1); then
    echo "REACHABLE $url status=$out"
  else
    echo "BLOCKED $url ($out)"
  fi
done
