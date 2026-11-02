#!/usr/bin/env bash
# F0-21: checks the separation between generator and verifier on the single F0 host
# (ADR-0011). Run it on that host from the code checkout. Host names, keys and paths
# come from an env file outside this repo (see README.md next to this script).
#
#   1. the task store is a 700 directory owned by the factory user;
#   2. no running container and no Harbor task or job directory reaches the store;
#   3. an agent sandbox (Harbor, network_mode = "allowlist") reaches the gateway only;
#   4. the verifier container (factory.verifier.sandbox) has no network at all;
#   5. an agent key cannot mint keys for the verifier team.
#
# Exit 0 only when every check passes.
set -uo pipefail

env_file="${FACTORY_ISOLATION_ENV:-$HOME/factory-f0/isolation.env}"
if [ ! -f "$env_file" ]; then
  echo "isolation-check: env file not found at $env_file" >&2
  exit 2
fi
# shellcheck source=/dev/null
. "$env_file"
for var in FACTORY_GATEWAY_URL FACTORY_STORE FACTORY_AGENT_KEY FACTORY_VERIFIER_TEAM FACTORY_HARBOR_DIRS; do
  if [ -z "${!var:-}" ]; then
    echo "isolation-check: $var is not set in $env_file" >&2
    exit 2
  fi
done
harbor="${FACTORY_HARBOR:-$HOME/.local/bin/uvx --from harbor==0.25.0 harbor}"
probe_image="${FACTORY_PROBE_IMAGE:-python:3.12-slim}"
gateway_host="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.urlsplit(sys.argv[1]).hostname)' "$FACTORY_GATEWAY_URL")"
gateway_port="$(python3 -c 'import sys, urllib.parse; u = urllib.parse.urlsplit(sys.argv[1]); print(u.port or (443 if u.scheme == "https" else 80))' "$FACTORY_GATEWAY_URL")"
store="$(realpath "$FACTORY_STORE")"
code_dir="$(cd "$(dirname "$0")/../.." && pwd)"
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT

failures=0
pass() { echo "PASS  $1"; }
fail() { echo "FAIL  $1"; failures=$((failures + 1)); }

# 1. Store permissions.
mode="$(stat -c '%a %U' "$store")"
if [ "$mode" = "700 $(id -un)" ]; then
  pass "store is 700 and owned by $(id -un)"
else
  fail "store mode/owner is '$mode', expected '700 $(id -un)'"
fi

# 2. Nothing a sandbox sees points into the store.
leaks=""
for id in $(docker ps -q); do
  sources="$(docker inspect -f '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}' "$id")"
  while IFS= read -r source; do
    [ -n "$source" ] || continue
    resolved="$(realpath -m "$source")"
    case "$resolved/" in
      "$store"/*) leaks="$leaks container $(docker inspect -f '{{.Name}}' "$id") mounts $source;" ;;
    esac
    case "$store/" in
      "$resolved"/*) leaks="$leaks container $(docker inspect -f '{{.Name}}' "$id") mounts $source, which contains the store;" ;;
    esac
  done <<<"$sources"
done
for dir in $FACTORY_HARBOR_DIRS; do
  [ -e "$dir" ] || continue
  resolved="$(realpath "$dir")"
  case "$resolved/" in
    "$store"/*) leaks="$leaks harbor dir $dir is inside the store;" ;;
  esac
  case "$store/" in
    "$resolved"/*) leaks="$leaks harbor dir $dir contains the store;" ;;
  esac
  while IFS= read -r -d '' link; do
    case "$(realpath -m "$link")/" in
      "$store"/*) leaks="$leaks symlink $link points into the store;" ;;
    esac
  done < <(find "$dir" -type l -print0 2>/dev/null)
done
if [ -z "$leaks" ]; then
  pass "no running container, Harbor task or job directory reaches the store"
else
  fail "store reachable:$leaks"
fi

# 3. Agent sandbox egress: the gateway answers, nothing else does.
task="$scratch/tasks/isolation-probe"
mkdir -p "$task/environment" "$task/solution" "$task/tests"
printf 'FROM %s\nWORKDIR /workspace\n' "$probe_image" >"$task/environment/Dockerfile"
printf 'Probe the network. (Used only with the oracle agent.)\n' >"$task/instruction.md"
cat >"$task/task.toml" <<EOF
schema_version = "1.4"
[verifier]
timeout_sec = 60.0
[agent]
timeout_sec = 120.0
[environment]
network_mode = "allowlist"
allowed_hosts = ["$gateway_host"]
EOF
cat >"$task/solution/solve.sh" <<EOF
#!/bin/bash
python - <<'PY' > /workspace/probe.json
import json, urllib.error, urllib.request
res = {}
targets = {"gateway": "$FACTORY_GATEWAY_URL/health/liveliness", "example": "https://example.com/", "github": "https://api.github.com/"}
for name, url in targets.items():
    try:
        urllib.request.urlopen(url, timeout=8)
        res[name] = "reachable"
    except urllib.error.HTTPError:
        res[name] = "reachable"  # the server answered, so the network let the request through
    except Exception as exc:
        res[name] = "unreachable: " + type(exc).__name__
print(json.dumps(res))
PY
EOF
cat >"$task/tests/test.sh" <<'EOF'
#!/bin/bash
mkdir -p /logs/verifier
cp /workspace/probe.json /logs/verifier/probe.json 2>/dev/null || echo '{}' >/logs/verifier/probe.json
python - <<'PY'
import json
p = json.load(open("/logs/verifier/probe.json"))
ok = p.get("gateway") == "reachable" and all(
    p.get(name, "").startswith("unreachable") for name in ("example", "github")
)
open("/logs/verifier/reward.txt", "w").write("1" if ok else "0")
PY
EOF
chmod +x "$task/solution/solve.sh" "$task/tests/test.sh"
$harbor run -p "$scratch/tasks" -a oracle -o "$scratch/jobs" --job-name isolation-probe >"$scratch/harbor.log" 2>&1
reward="$(find "$scratch/jobs" -path '*/verifier/reward.txt' -exec cat {} \; 2>/dev/null | head -1)"
probe="$(find "$scratch/jobs" -path '*/verifier/probe.json' -exec cat {} \; 2>/dev/null | head -1)"
if [ "$reward" = 1 ]; then
  pass "agent sandbox reaches the gateway and nothing else ($probe)"
else
  fail "agent sandbox egress: reward '${reward:-none}', probe ${probe:-missing}; see tail of harbor log:"
  tail -5 "$scratch/harbor.log" | sed 's/^/      /'
fi

# 4. The verifier container has no network.
docker pull -q "$probe_image" >/dev/null
pinned="$(docker image inspect -f '{{index .RepoDigests 0}}' "$probe_image")"
verifier_out="$(
  cd "$code_dir" && "$HOME/.local/bin/uv" run -q --locked python - "$pinned" "$gateway_host" "$gateway_port" "$scratch" <<'PY'
import shlex
import sys
from pathlib import Path

from factory.verifier.sandbox import DockerSandbox, RunRequest

image, host, port, scratch = sys.argv[1], sys.argv[2], sys.argv[3], Path(sys.argv[4])
workspace, logs = scratch / "workspace", scratch / "logs"
workspace.mkdir()
logs.mkdir()
logs.chmod(0o777)
probe = (
    "import socket\n"
    "try:\n"
    f"    socket.create_connection(({host!r}, {port}), 5)\n"
    "    print('REACHED')\n"
    "except OSError as exc:\n"
    "    print('BLOCKED', type(exc).__name__)\n"
)
result = DockerSandbox().run(
    RunRequest(
        image=image,
        workspace=workspace,
        logs_dir=logs,
        command=f"python -c {shlex.quote(probe)}",
        timeout_s=60,
        workdir="/workspace",
    )
)
print(result.stdout_tail.strip() or result.stderr_tail.strip())
PY
)"
case "$verifier_out" in
  *BLOCKED*) pass "verifier container cannot reach the gateway (${verifier_out##*BLOCKED })" ;;
  *) fail "verifier container network: '$verifier_out'" ;;
esac

# 5. An agent key cannot mint verifier keys. A 401 from an invalid key proves nothing,
# so the key must first work for an ordinary request.
models="$(curl -s -o /dev/null -w '%{http_code}' "$FACTORY_GATEWAY_URL/v1/models" \
  -H "Authorization: Bearer $FACTORY_AGENT_KEY")"
if [ "$models" != 200 ]; then
  fail "agent key is not valid (GET /v1/models returned HTTP $models), so check 5 cannot run"
else
code="$(curl -s -o "$scratch/mint.json" -w '%{http_code}' -X POST "$FACTORY_GATEWAY_URL/key/generate" \
  -H "Authorization: Bearer $FACTORY_AGENT_KEY" -H 'Content-Type: application/json' \
  -d "{\"team_id\": \"$FACTORY_VERIFIER_TEAM\", \"max_budget\": 0.01, \"duration\": \"5m\"}")"
case "$code" in
  401 | 403) pass "agent key cannot mint verifier keys (HTTP $code)" ;;
  *)
    fail "agent key minting a verifier key returned HTTP $code"
    if grep -q '"key"' "$scratch/mint.json"; then
      echo "      a key WAS created (expires in 5 minutes); revoke it with the master key" >&2
    fi
    ;;
esac
fi

if [ "$failures" -eq 0 ]; then
  echo "isolation-check: all checks passed"
  exit 0
fi
echo "isolation-check: $failures check(s) failed" >&2
exit 1
