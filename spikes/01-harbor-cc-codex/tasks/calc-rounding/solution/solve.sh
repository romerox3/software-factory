#!/bin/bash
set -e
cat > /workspace/src/calc.py <<'PY'
def divide_round(a: int, b: int) -> int:
    """Divide a by b and round half to even."""
    return round(a / b)
PY
