#!/bin/bash
python - <<'PY' > /workspace/probe.json
import json, urllib.request
res = {}
for name, url in {"allowed": "https://pypi.org/simple/", "blocked": "https://example.com/", "github": "https://api.github.com/"}.items():
    try:
        urllib.request.urlopen(url, timeout=8); res[name] = "reachable"
    except Exception as e:
        res[name] = "unreachable: " + type(e).__name__
print(json.dumps(res))
PY
