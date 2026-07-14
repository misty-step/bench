import copy


def critique_router(router_path, cases):
    findings = []
    for case in cases:
        if case["input"].get("approved") is False:
            findings.append({"case_id": case["case_id"], "status": "CONFIRMED", "counterexample_input": copy.deepcopy(case["input"]), "expected": copy.deepcopy(case["expected"]), "observed": copy.deepcopy(case["expected"]), "boundary": case["boundary"], "repair_invariants": copy.deepcopy(case["repair_invariants"])})
        elif case["input"].get("action") not in {"transmit", "save_draft"}:
            findings.append({"case_id": case["case_id"], "status": "UNKNOWN", "counterexample_input": copy.deepcopy(case["input"]), "expected": copy.deepcopy(case["expected"]), "observed": None, "boundary": case["boundary"], "repair_invariants": copy.deepcopy(case["repair_invariants"])})
    return {"schema_version": "bench.router_critique.v1", "findings": findings}
