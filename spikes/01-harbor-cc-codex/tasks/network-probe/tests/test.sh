#!/bin/bash
mkdir -p /logs/verifier; cp /workspace/probe.json /logs/verifier/probe.json 2>/dev/null || echo '{}' > /logs/verifier/probe.json
python - <<'PY'
import json; p = json.load(open("/logs/verifier/probe.json"))
ok = p.get("allowed") == "reachable" and p.get("blocked","").startswith("unreachable") and p.get("github","").startswith("unreachable")
open("/logs/verifier/reward.txt","w").write("1" if ok else "0")
PY
