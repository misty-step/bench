#!/usr/bin/env python3
"""Run one public lease operation in an isolated candidate process."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import time


def load(repo: Path):
    spec = importlib.util.spec_from_file_location("candidate_lease_store", repo / "lease_store.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("lease_store.py cannot be imported")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def receipt_is_blocked() -> bool:
    try:
        Path(os.environ["BENCH_RECEIPT_CANARY"]).write_text("forged\n")
    except PermissionError:
        return True
    return False


def wait_for_gate(path: str | None) -> None:
    if path is None:
        return
    deadline = time.monotonic() + 10
    gate = Path(path)
    while not gate.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("concurrency start gate did not open")
        time.sleep(0.005)


def main(repo: Path) -> None:
    request = json.loads(sys.stdin.read())
    report: dict = {"receipt_write_blocked": receipt_is_blocked()}
    try:
        candidate = load(repo)
        store = candidate.LeaseStore(request["path"])
        wait_for_gate(request.get("start_gate"))
        operation = request["operation"]
        if operation == "acquire":
            value = store.acquire(request["owner"], request["now"], request["ttl"])
        elif operation == "renew":
            value = store.renew(request["owner"], request["now"], request["ttl"])
        elif operation == "holder":
            value = store.holder(request["now"])
        else:
            raise ValueError(f"unknown operation {operation!r}")
        report.update({"result": value, "error": None})
    except Exception as exc:  # the verifier reports candidate failure as data
        report.update({"result": None, "error": f"{type(exc).__name__}: {exc}"})
    print(json.dumps(report))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
