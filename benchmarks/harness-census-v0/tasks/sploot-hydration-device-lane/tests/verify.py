#!/usr/bin/env python3
"""Harbor verifier boundary; hidden grading stays outside the worker image."""
from __future__ import annotations
import json
from pathlib import Path
import sys


def finish(payload: dict, code: int) -> None:
    directory = Path("/logs/verifier")
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o755)
    reward = directory / "reward.json"
    reward.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    reward.chmod(0o644)
    raise SystemExit(code)


if len(sys.argv) != 2:
    finish({"status": "invalid", "reason": "candidate repository argument is required"}, 2)
finish({"status": "deferred", "reason": "campaign grader is mounted outside the worker image"}, 2)
