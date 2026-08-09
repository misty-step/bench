#!/bin/sh
set -eu
fixture_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
grader="$fixture_dir/../grader.py"
if [ -f "$grader" ]; then
  output=$(python3 "$grader" "$fixture_dir/../environment/repo" 2>&1 || true)
  report=$(printf '%s' "$output" | tail -n 1)
  printf '%s' "$report" | python3 -c 'import json,sys
r=json.load(sys.stdin)
assert r["passed"] is False
assert r["passed_checks"] == 0
assert r["task_points"] == 0.0
assert isinstance(r["failed_check"], str) and r["failed_check"]'
fi
exec python3 "$fixture_dir/verify.py" "$@"
