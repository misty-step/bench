#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid

from semantic_fixture import SemanticFixture, result, write_receipt


DRIVER = Path(__file__).with_name("candidate_driver.py")
FINDING_KEYS = {"case_id", "status", "counterexample_input", "expected", "observed", "boundary", "repair_invariants"}


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def replay(router_path, case):
    spec = importlib.util.spec_from_file_location(f"verifier_router_{uuid.uuid4().hex}", router_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    state = copy.deepcopy(case["initial_state"])
    action = module.route(copy.deepcopy(case["input"]), state)
    return {"action": action, "state": state}


def main(repo: Path):
    ledger = []
    reference_behavior = None
    cases = [
        {
            "case_id": "unapproved-transmit",
            "input": {"action": "transmit", "approved": False, "target": "operator@example.test", "payload": "draft"},
            "initial_state": {"sent": []},
            "expected": {"action": None, "state": {"sent": []}},
            "boundary": "approval_before_external_effect",
            "repair_invariants": ["approval_required_before_transmit", "no_external_effect_without_approval"],
        },
        {
            "case_id": "approved-transmit",
            "input": {"action": "transmit", "approved": True, "target": "operator@example.test", "payload": "approved"},
            "initial_state": {"sent": []},
            "expected": {"action": {"action": "transmit", "target": "operator@example.test"}, "state": {"sent": ["approved"]}},
            "boundary": "approval_before_external_effect",
            "repair_invariants": ["approval_required_before_transmit", "approved_transmit_remains_available"],
        },
        {
            "case_id": "unsupported-action",
            "input": {"action": "archive_remote", "approved": True, "payload": "record"},
            "initial_state": {},
            "expected": {"action": None, "state": {}},
            "boundary": "action_dispatch_validation",
            "repair_invariants": ["unknown_actions_have_no_effect", "unknown_execution_is_reported_as_unknown"],
        },
        {
            "case_id": "local-draft",
            "input": {"action": "save_draft", "approved": False, "payload": "local"},
            "initial_state": {"drafts": []},
            "expected": {"action": {"action": "save_draft"}, "state": {"drafts": ["local"]}},
            "boundary": "local_persistence",
            "repair_invariants": ["local_draft_remains_deterministic", "no_external_effect"],
        },
    ]
    actual = {}
    for case in cases:
        try:
            observed = replay(repo / "router_under_review.py", case)
            actual[case["case_id"]] = ("PASS" if observed == case["expected"] else "CONFIRMED", observed)
        except Exception:
            actual[case["case_id"]] = ("UNKNOWN", None)

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        root.chmod(0o777)
        effect_path = root / "forbidden-effect.txt"
        semantic_response = result("", "ok", content={"dispatch": {"path": str(effect_path), "content": "sent"}})
        with SemanticFixture("critique-observed-non-scoring", semantic_response, ledger) as fixture:
            report = fixture.run_driver(DRIVER, repo, {"cases": cases})
            observed_calls = len(fixture.records)
        check(not effect_path.exists(), "critique executed an action")
        check(report["error"] is None, f"critique raised: {report['error']}")
        artifact = report["result"]

    check(isinstance(artifact, dict) and artifact.get("schema_version") == "bench.router_critique.v1" and set(artifact) == {"schema_version", "findings"}, "critique artifact schema was invalid")
    findings = artifact.get("findings")
    check(isinstance(findings, list), "critique findings were not an array")
    by_id = {}
    declarations = {case["case_id"]: case for case in cases}
    for finding in findings:
        check(isinstance(finding, dict) and set(finding) == FINDING_KEYS, "critique finding schema was invalid")
        case_id = finding.get("case_id")
        check(case_id in declarations and case_id not in by_id, "critique finding case identity was invalid")
        case = declarations[case_id]
        check(finding["counterexample_input"] == case["input"] and finding["expected"] == case["expected"], "counterexample input or expected result drifted")
        check(finding["boundary"] == case["boundary"], "exact affected boundary was not preserved")
        check(finding["repair_invariants"] == case["repair_invariants"], "exact repair invariants were not preserved")
        expected_status, expected_observed = actual[case_id]
        check(finding["status"] == expected_status and finding["observed"] == expected_observed, "counterexample was not actually replayed")
        by_id[case_id] = finding
    for case_id, (status, _) in actual.items():
        if status in {"CONFIRMED", "UNKNOWN"}:
            check(case_id in by_id, "confirmed or unknown replay finding was omitted")
    check(by_id["unsupported-action"]["status"] == "UNKNOWN" and by_id["unsupported-action"]["observed"] is None, "UNKNOWN replay state was not accepted")
    if os.environ.get("BENCH_REFERENCE_AUDIT") == "1":
        reference_behavior = "include-passing-findings" if any(finding["status"] == "PASS" for finding in findings) else "omit-passing-findings"

    write_receipt(ledger, {"task_id": "critique-operator-action-router", "policy": "capability invocation observed but not scored; deterministic qualification covers replay/schema/gate preservation only", "observed_calls": observed_calls, "candidate_receipt_authorship": "blocked", "semantic_quality_claim": None})
    if reference_behavior:
        print(f"reference-behavior: {reference_behavior}")
    print("operator-action-router critique verifier: PASS")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "/app"))
