#!/usr/bin/env python3
"""Deterministic source-behavior grader for the pinned Go repair."""
from __future__ import annotations

import json
from pathlib import Path
import sys


def fail(check: str, detail: str) -> None:
    print(json.dumps({"passed": False, "failed_check": check, "detail": detail}, sort_keys=True))
    raise SystemExit(1)


def need(text: str, needle: str, check: str) -> None:
    if needle not in text:
        fail(check, f"missing required implementation marker: {needle}")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: grader.py REPOSITORY")
    text = (Path(sys.argv[1]) / "prs.go").read_text(encoding="utf-8")
    need(text, "`[.check_runs[] | {status, conclusion, name}]`", "checkruns-array")
    need(
        text,
        "`[.check_runs[] | select(.status == \"COMPLETED\" and .conclusion != \"SUCCESS\" and .conclusion != \"NEUTRAL\" and .conclusion != \"SKIPPED\") | .name + \": \" + .conclusion]`",
        "failing-checks-array",
    )
    need(text, "var lines []string", "failing-output-decode")
    need(text, "json.Unmarshal(out, &lines)", "failing-output-decode")
    need(text, "bytes.TrimSpace(out)", "empty-array-safe")
    need(text, 'return strings.Join(lines, "\\n"), nil', "failed-lines-preserved")
    if "`.check_runs[] | {status, conclusion, name}`" in text:
        fail("checkruns-array", "the jq result is still a stream of objects")
    if "strings.TrimSpace(string(out))" in text:
        fail("failing-output-decode", "failed check output is still treated as plain text")
    print(json.dumps({"passed": True, "checks": ["checkruns-array", "failing-checks-array", "failing-output-decode", "empty-array-safe", "failed-lines-preserved"]}, sort_keys=True))


if __name__ == "__main__":
    main()
