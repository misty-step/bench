import copy
import importlib.util
import uuid


def critique_router(router_path, cases):
    findings = []
    for case in cases:
        try:
            spec = importlib.util.spec_from_file_location(f"router_{uuid.uuid4().hex}", router_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            state = copy.deepcopy(case["initial_state"])
            action = module.route(copy.deepcopy(case["input"]), state)
            observed = {"action": action, "state": state}
            status = "PASS" if observed == case["expected"] else "CONFIRMED"
        except Exception:
            observed, status = None, "UNKNOWN"
        if status == "PASS":
            continue
        rendered = str(case["input"]).lower()
        boundary = "approval_before_external_effect" if "send" in rendered else "semantic_intent"
        findings.append({"case_id": case["case_id"], "status": status, "counterexample_input": copy.deepcopy(case["input"]), "expected": copy.deepcopy(case["expected"]), "observed": observed, "boundary": boundary, "repair_invariants": copy.deepcopy(case["repair_invariants"])})
    return {"schema_version": "bench.router_critique.v1", "findings": findings}
