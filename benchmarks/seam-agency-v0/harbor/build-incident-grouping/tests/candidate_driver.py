#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys


def load(repo: Path):
    spec = importlib.util.spec_from_file_location("candidate_incident_store", repo / "incident_store.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("incident_store.py cannot be imported")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def receipt_is_blocked() -> bool:
    try:
        Path(os.environ["BENCH_RECEIPT_CANARY"]).write_text("forged\n")
    except PermissionError:
        return True
    return False


def main(repo: Path) -> None:
    request = json.loads(sys.stdin.read())
    report = {"receipt_write_blocked": receipt_is_blocked()}
    try:
        store = load(repo).IncidentStore(request["path"])
        if request["operation"] == "ingest":
            report["result"] = store.ingest(request["report_id"], request["text"])
        else:
            report["result"] = store.groups()
        report["error"] = None
    except Exception as exc:
        report["result"] = None
        report["error"] = f"{type(exc).__name__}: {exc}"
    print(json.dumps(report))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
