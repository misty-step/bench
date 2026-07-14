from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import uuid


def _replay(router_path, case):
    spec = importlib.util.spec_from_file_location(f"router_{uuid.uuid4().hex}", Path(router_path))
    if spec is None or spec.loader is None:
        raise RuntimeError("router cannot be imported")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    state = copy.deepcopy(case["initial_state"])
    action = module.route(copy.deepcopy(case["input"]), state)
    return {"action": action, "state": state}


def _finding(case, status, observed):
    return {
        "case_id": case["case_id"],
        "status": status,
        "counterexample_input": copy.deepcopy(case["input"]),
        "expected": copy.deepcopy(case["expected"]),
        "observed": observed,
        "boundary": case["boundary"],
        "repair_invariants": copy.deepcopy(case["repair_invariants"]),
    }


def critique_router(router_path, cases):
    findings = []
    for case in cases:
        try:
            observed = _replay(router_path, case)
        except Exception:
            findings.append(_finding(case, "UNKNOWN", None))
            continue
        if observed != case["expected"]:
            findings.append(_finding(case, "CONFIRMED", observed))
    return {"schema_version": "bench.router_critique.v1", "findings": findings}
