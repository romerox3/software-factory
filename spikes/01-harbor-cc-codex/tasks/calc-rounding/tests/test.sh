#!/bin/bash
# Hidden FAIL_TO_PASS tests: only the verifier sees them.
mkdir -p /logs/verifier
cat > /tmp/test_hidden.py <<'PY'
import sys; sys.path.insert(0, "/workspace")
from src.calc import divide_round
def test_half_even_down(): assert divide_round(5, 2) == 2
def test_half_even_up(): assert divide_round(7, 2) == 4
PY
cd /workspace && git diff > /logs/verifier/diff.patch || true
if python -m pytest -q /tmp/test_hidden.py tests/ > /logs/verifier/pytest.txt 2>&1; then echo 1 > /logs/verifier/reward.txt; else echo 0 > /logs/verifier/reward.txt; fi
