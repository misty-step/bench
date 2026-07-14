#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

from semantic_fixture import SemanticFixture, result, write_receipt


DRIVER = Path(__file__).with_name("candidate_driver.py")


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def invoke(fixture, repo, operation, capability_present=True, **values):
    report = fixture.run_driver(DRIVER, repo, {"operation": operation, **values}, capability_present=capability_present)
    check(report["error"] is None, f"{operation} raised: {report['error']}")
    return report["result"]


def expected_identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def main(repo: Path):
    ledger = []
    reference_behavior = None
    response = result("", "ok", content={"changed_axes": ["reasoning_effort"]})
    base = {"model": "atlas", "provider": "north", "temperature": 0, "tools": ["files"]}
    low = {**base, "reasoning_effort": "low"}
    high = {**base, "reasoning_effort": "high"}
    explicit_default = {**base, "reasoning_effort": "default"}

    with SemanticFixture("deterministic-attribution", response, ledger) as fixture:
        base_id = invoke(fixture, repo, "identity", config=base)
        low_id = invoke(fixture, repo, "identity", config=low)
        high_id = invoke(fixture, repo, "identity", config=high)
        default_id = invoke(fixture, repo, "identity", config=explicit_default)
        reasoning_change = invoke(fixture, repo, "diff", left=low, right=high)
        missing_change = invoke(fixture, repo, "diff", left=base, right=explicit_default)
        multi_change = invoke(fixture, repo, "diff", left=low, right={**high, "provider": "south", "new_axis": 2})
        invalid_identity = invoke(fixture, repo, "identity", config=["not", "an", "object"])
        invalid_diff = invoke(fixture, repo, "diff", left=[], right={})
        check(not fixture.records, "semantic capability invoked for comparison attribution")

    check(low_id == expected_identity(low) and high_id == expected_identity(high) and low_id != high_id, "reasoning effort was not identity-bearing")
    check(base_id != default_id and low_id != default_id, "missing reasoning effort collapsed into explicit value")
    check(base_id == expected_identity(base), "existing configuration identity compatibility changed")
    check(reasoning_change == ["reasoning_effort"] and missing_change == ["reasoning_effort"], "only the changed reasoning axis was not attributed")
    check(set(multi_change) == {"reasoning_effort", "provider", "new_axis"}, "multi-axis attribution lost or invented an axis")
    if os.environ.get("BENCH_REFERENCE_AUDIT") == "1":
        if multi_change == ["new_axis", "provider", "reasoning_effort"]:
            reference_behavior = "alphabetical-attribution-order"
        elif multi_change == ["provider", "reasoning_effort", "new_axis"]:
            reference_behavior = "declared-axis-priority-order"
        else:
            raise AssertionError(f"unrecognized multi-axis attribution order: {multi_change}")
    check(invalid_identity is None and invalid_diff == [], "invalid comparison inputs were accepted")

    with SemanticFixture("capability-absent", response, ledger) as fixture:
        absent_id = invoke(fixture, repo, "identity", capability_present=False, config=high)
        absent_change = invoke(fixture, repo, "diff", capability_present=False, left=low, right=high)
    check(absent_id == high_id and absent_change == ["reasoning_effort"], "comparison attribution failed with capability absent and network denied")

    write_receipt(ledger, {"task_id": "extend-comparison-attribution", "policy": "semantic.generate.v1 calls must be zero", "observed_calls": 0, "capability_absent_recheck": "pass", "network": "explicit Harbor no-network baseline; no credentials provided", "candidate_receipt_authorship": "blocked"})
    if reference_behavior:
        print(f"reference-behavior: {reference_behavior}")
    print("comparison-attribution verifier: PASS")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "/app"))
