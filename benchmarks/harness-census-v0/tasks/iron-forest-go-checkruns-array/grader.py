#!/usr/bin/env python3
"""Offline behavioral grader for the pinned Go check-run repair."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import shutil


def fail(check: str, detail: str) -> None:
    print(json.dumps({"passed": False, "failed_check": check, "detail": detail}, sort_keys=True))
    raise SystemExit(1)


TEST = r'''package main

import (
	"os"
	"testing"
)

func TestHarnessCensusCheckRuns(t *testing.T) {
	failing, err := failingChecks("owner/repo", "sha")
	if err != nil || failing != "lint: FAILURE\ne2e: CANCELLED" {
		t.Fatalf("failing checks = %q, err = %v", failing, err)
	}
	rollup, err := checkRollup("owner/repo", "sha")
	if err != nil || rollup != "fail" {
		t.Fatalf("rollup = %q, err = %v", rollup, err)
	}
	if err := os.Setenv("HARNESS_CENSUS_EMPTY_CHECKS", "1"); err != nil {
		t.Fatal(err)
	}
	emptyFailing, err := failingChecks("owner/repo", "sha")
	if err != nil || emptyFailing != "" {
		t.Fatalf("empty failing checks = %q, err = %v", emptyFailing, err)
	}
	empty, err := checkRollup("owner/repo", "sha")
	if err != nil || empty != "" {
		t.Fatalf("empty rollup = %q, err = %v", empty, err)
	}
	if err := os.Unsetenv("HARNESS_CENSUS_EMPTY_CHECKS"); err != nil {
		t.Fatal(err)
	}
}
'''

GH = r'''#!/bin/sh
set -eu
array_query=false
if printf '%s\n' "$*" | grep -Eq -- '-q[[:space:]]*\['; then
  array_query=true
fi
if [ "${HARNESS_CENSUS_EMPTY_CHECKS:-}" = 1 ]; then
  if $array_query; then printf '%s\n' '[]'; else exit 0; fi
elif printf '%s\n' "$*" | grep -q select; then
  if $array_query; then printf '%s\n' '["lint: FAILURE","e2e: CANCELLED"]'; else printf '%s\n' '"lint: FAILURE"' '"e2e: CANCELLED"'; fi
elif $array_query; then
  printf '%s\n' '[{"status":"COMPLETED","conclusion":"FAILURE","name":"lint"},{"status":"COMPLETED","conclusion":"SUCCESS","name":"tests"},{"status":"COMPLETED","conclusion":"CANCELLED","name":"e2e"}]'
else
  printf '%s\n' '{"status":"COMPLETED","conclusion":"FAILURE","name":"lint"}'
  printf '%s\n' '{"status":"COMPLETED","conclusion":"SUCCESS","name":"tests"}'
  printf '%s\n' '{"status":"COMPLETED","conclusion":"CANCELLED","name":"e2e"}'
fi
'''

def run_test(repo: Path, test: str) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="harness-census-go-") as temporary:
        root = Path(temporary)
        test_path = repo / "harness_census_oracle_test.go"
        gh_path = root / "gh"
        try:
            test_path.write_text(test, encoding="utf-8")
            gh_path.write_text(GH, encoding="utf-8")
            gh_path.chmod(gh_path.stat().st_mode | stat.S_IXUSR)
            env = os.environ.copy()
            env["PATH"] = f"{root}:{env.get('PATH', '')}"
            env.update({"GOTOOLCHAIN": "local", "GOPROXY": "off", "GOSUMDB": "off"})
            result = subprocess.run(
                ([shutil.which("go")] if shutil.which("go") else [shutil.which("mise"), "exec", "go@1.26.5", "--", "go"]) + ["test", "-run", "^TestHarnessCensusCheckRuns$", "-count=1", "."],
                cwd=repo,
                env=env,
                text=True,
                capture_output=True,
                timeout=180,
                check=False,
            )
            return result.returncode, (result.stdout + result.stderr)[-4000:]
        except (OSError, subprocess.SubprocessError) as error:
            return 1, str(error)
        finally:
            test_path.unlink(missing_ok=True)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: grader.py REPOSITORY")
    repo = Path(sys.argv[1]).resolve()
    source = repo / "prs.go"
    if not source.is_file():
        fail("invalid-syntax", "target prs.go is missing")
    code, output = run_test(repo, TEST)
    if code:
        if "failing checks =" in output:
            if 'failing checks = "[' in output:
                fail("failing-output-decode", output)
            fail("failing-checks-array", output)
        if "rollup =" in output:
            fail("failing-checks-array", output)
        fail("invalid-syntax", output)
    print(json.dumps({"passed": True, "checks": ["checkruns-array", "multiple-failures", "empty-array-safe", "failing-output-decode"]}, sort_keys=True))


if __name__ == "__main__":
    main()
