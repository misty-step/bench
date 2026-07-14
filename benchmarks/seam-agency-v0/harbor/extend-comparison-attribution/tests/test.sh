#!/bin/sh
set -eu
mkdir -p /logs/verifier
chmod 0700 /logs/verifier
chmod 0555 /tests/crucible-semantic
if BENCH_REQUIRE_ISOLATION=1 PATH="/tests:$PATH" python3 /tests/verify.py /app; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
  exit 1
fi
