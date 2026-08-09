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


CHECKS = ("checkruns-array", "multiple-failures", "empty-array-safe", "failing-output-decode", "gh-api-query")


def fail(check: str, detail: str, passed_checks: int = 0) -> None:
    total_checks = len(CHECKS)
    print(json.dumps({"passed": False, "hard_pass": False, "passed_checks": passed_checks, "total_checks": total_checks, "task_points": passed_checks / total_checks, "failed_check": check, "detail": detail}, sort_keys=True))
    raise SystemExit(1)


TEST = r'''package main

import (
    "fmt"
    "os"
    "strings"
    "testing"
)

func requireCallLog(t *testing.T, path string, endpoints ...string) {
    t.Helper()
    raw, err := os.ReadFile(path)
    if err != nil {
        t.Fatal(err)
    }
    calls := strings.Split(strings.TrimSpace(string(raw)), "\n")
    for _, endpoint := range endpoints {
        found := false
        for _, call := range calls {
            if strings.Contains(call, "api "+endpoint+" -q [") && strings.Contains(call, ".check_runs") && strings.Contains(call, "status") && strings.Contains(call, "conclusion") && strings.Contains(call, "name") {
                found = true
                break
            }
        }
        if !found {
            t.Fatalf("missing instrumented gh api/query call for %s: %q", endpoint, string(raw))
        }
    }
}

func TestHarnessCensusCheckRuns(t *testing.T) {
    logPath := t.TempDir() + "/gh-calls.log"
    if err := os.Setenv("HARNESS_CENSUS_GH_LOG", logPath); err != nil {
        t.Fatal(err)
    }
    failing, err := failingChecks("owner/repo", "sha")
    if err != nil || failing != "lint: FAILURE\ne2e: CANCELLED" {
        t.Fatalf("failing checks = %q, err = %v", failing, err)
    }
    fmt.Println("HARNESS_CENSUS_PASS:multiple-failures")

    rollup, err := checkRollup("owner/repo", "sha")
    if err != nil || rollup != "fail" {
        t.Fatalf("rollup = %q, err = %v", rollup, err)
    }
    fmt.Println("HARNESS_CENSUS_PASS:checkruns-array")

    alternate, err := failingChecks("acme/project", "other")
    if err != nil || alternate != "build: ACTION_REQUIRED\ndeploy: TIMED_OUT" {
        t.Fatalf("alternate failing checks = %q, err = %v", alternate, err)
    }
    fmt.Println("HARNESS_CENSUS_PASS:failing-output-decode")

    if err := os.Setenv("HARNESS_CENSUS_EMPTY_CHECKS", "1"); err != nil {
        t.Fatal(err)
    }
    emptyFailing, err := failingChecks("empty/repo", "zero")
    if err != nil || emptyFailing != "" {
        t.Fatalf("empty failing checks = %q, err = %v", emptyFailing, err)
    }
    empty, err := checkRollup("empty/repo", "zero")
    if err != nil || empty != "" {
        t.Fatalf("empty rollup = %q, err = %v", empty, err)
    }
    if err := os.Unsetenv("HARNESS_CENSUS_EMPTY_CHECKS"); err != nil {
        t.Fatal(err)
    }
    fmt.Println("HARNESS_CENSUS_PASS:empty-array-safe")

    requireCallLog(t, logPath,
        "repos/owner/repo/commits/sha/check-runs",
        "repos/acme/project/commits/other/check-runs",
        "repos/empty/repo/commits/zero/check-runs",
    )
    fmt.Println("HARNESS_CENSUS_PASS:gh-api-query")
}
'''

GH = r'''#!/bin/sh
set -eu
printf '%s\n' "$*" >> "${HARNESS_CENSUS_GH_LOG:?}"
array_query=false
case "$*" in *"-q ["*) array_query=true;; esac
endpoint="$*"
if [ "${HARNESS_CENSUS_EMPTY_CHECKS:-}" = 1 ] || printf '%s' "$endpoint" | grep -q 'repos/empty/repo/commits/zero/check-runs'; then
  if $array_query; then printf '%s\n' '[]'; else exit 0; fi
elif printf '%s' "$endpoint" | grep -q 'repos/acme/project/commits/other/check-runs'; then
  if printf '%s' "$endpoint" | grep -q select; then
    if $array_query; then printf '%s\n' '["build: ACTION_REQUIRED","deploy: TIMED_OUT"]'; else printf '%s\n' '"build: ACTION_REQUIRED"' '"deploy: TIMED_OUT"'; fi
  elif $array_query; then
    printf '%s\n' '[{"status":"COMPLETED","conclusion":"ACTION_REQUIRED","name":"build"},{"status":"COMPLETED","conclusion":"NEUTRAL","name":"docs"},{"status":"COMPLETED","conclusion":"TIMED_OUT","name":"deploy"}]'
  else
    printf '%s\n' '{"status":"COMPLETED","conclusion":"ACTION_REQUIRED","name":"build"}' '{"status":"COMPLETED","conclusion":"NEUTRAL","name":"docs"}' '{"status":"COMPLETED","conclusion":"TIMED_OUT","name":"deploy"}'
  fi
elif printf '%s' "$endpoint" | grep -q 'repos/owner/repo/commits/sha/check-runs'; then
  if printf '%s' "$endpoint" | grep -q select; then
    if $array_query; then printf '%s\n' '["lint: FAILURE","e2e: CANCELLED"]'; else printf '%s\n' '"lint: FAILURE"' '"e2e: CANCELLED"'; fi
  elif $array_query; then
    printf '%s\n' '[{"status":"COMPLETED","conclusion":"FAILURE","name":"lint"},{"status":"COMPLETED","conclusion":"SUCCESS","name":"tests"},{"status":"COMPLETED","conclusion":"CANCELLED","name":"e2e"}]'
  else
    printf '%s\n' '{"status":"COMPLETED","conclusion":"FAILURE","name":"lint"}' '{"status":"COMPLETED","conclusion":"SUCCESS","name":"tests"}' '{"status":"COMPLETED","conclusion":"CANCELLED","name":"e2e"}'
  fi
else
  echo "unexpected gh api endpoint: $endpoint" >&2
  exit 2
fi
'''


def run_test(repo: Path, test: str) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="harness-census-go-") as temporary:
        root = Path(temporary)
        test_path = repo / "harness_census_oracle_test.go"
        gh_path = root / "gh"
        log_path = root / "gh-calls.log"
        try:
            test_path.write_text(test, encoding="utf-8")
            gh_path.write_text(GH, encoding="utf-8")
            gh_path.chmod(gh_path.stat().st_mode | stat.S_IXUSR)
            env = os.environ.copy()
            env["PATH"] = f"{root}:{env.get('PATH', '')}"
            env["HARNESS_CENSUS_GH_LOG"] = str(log_path)
            env.update({"GOTOOLCHAIN": "local", "GOPROXY": "off", "GOSUMDB": "off"})
            go = shutil.which("go") or shutil.which("mise")
            command = [go, "test", "-v", "-run", "^TestHarnessCensusCheckRuns$", "-count=1", "."] if go and go.endswith("go") else [go, "exec", "go@1.26.5", "--", "go", "test", "-v", "-run", "^TestHarnessCensusCheckRuns$", "-count=1", "."]
            result = subprocess.run(command, cwd=repo, env=env, text=True, capture_output=True, timeout=180, check=False)
            return result.returncode, (result.stdout + result.stderr)[-6000:]
        except (OSError, subprocess.SubprocessError) as error:
            return 1, str(error)
        finally:
            test_path.unlink(missing_ok=True)


_COMPILE_FAILURE_MARKERS = ("cannot find package", "build failed", "# command-line-arguments", "undefined:", "syntax error:", "expected declaration")


def _compile_failure(output: str) -> bool:
    return any(marker in output for marker in _COMPILE_FAILURE_MARKERS)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: grader.py REPOSITORY")
    repo = Path(sys.argv[1]).resolve()
    source = repo / "prs.go"
    if not source.is_file():
        fail("checkruns-array", "target prs.go is missing")
    code, output = run_test(repo, TEST)
    if code:
        failed = "invalid-syntax"
        for check, marker in (
            ("gh-api-query", "missing instrumented gh api/query"),
            ("failing-output-decode", "alternate failing checks"),
            ("failing-output-decode", r'failing checks = "[\"'),
            ("empty-array-safe", "empty "),
            ("multiple-failures", "failing checks ="),
            ("checkruns-array", "rollup ="),
        ):
            if failed == "invalid-syntax" and marker in output:
                failed = check
                break
        if failed == "invalid-syntax" and not _compile_failure(output):
            failed = "behavior-mismatch"
        fail(failed, output)
    passed = sum(f"HARNESS_CENSUS_PASS:{check}" in output for check in CHECKS)
    if passed != len(CHECKS):
        fail("behavior-mismatch", output)
    total_checks = len(CHECKS)
    print(json.dumps({"passed": True, "hard_pass": True, "passed_checks": total_checks, "total_checks": total_checks, "task_points": 1.0, "checks": list(CHECKS)}, sort_keys=True))


if __name__ == "__main__":
    main()
