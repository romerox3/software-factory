#!/usr/bin/env bash
# T15: the snapshot must not carry the original history.
set -uo pipefail

echo "== remotes =="
git remote -v || true
echo "== refs =="
git for-each-ref --format='%(refname) %(objectname:short) %(subject)' || true
echo "== log --all =="
git log --all --oneline --decorate | head -n 50 || true
echo "== fsck --lost-found =="
git fsck --lost-found 2>&1 | head -n 50 || true
echo "== unreachable objects =="
git fsck --no-reflogs --unreachable 2>&1 | head -n 50 || true
