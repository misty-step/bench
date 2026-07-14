from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys


RUNNER = r'''
import copy, importlib.util, json, pathlib, sys
router_path = pathlib.Path(sys.argv[1])
case = json.loads(sys.stdin.read())
spec = importlib.util.spec_from_file_location("isolated_router", router_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
state = copy.deepcopy(case["initial_state"])
action = module.route(copy.deepcopy(case["input"]), state)
print(json.dumps({"action": action, "state": state}))
'''


def critique_router(router_path, cases):
    findings = []
    for case in cases:
        try:
            completed = subprocess.run([sys.executable, "-c", RUNNER, str(Path(router_path))], input=json.dumps(case), text=True, capture_output=True, timeout=5, check=False)
            if completed.returncode != 0:
                raise RuntimeError(completed.stderr)
            observed = json.loads(completed.stdout)
            status = "PASS" if observed == case["expected"] else "CONFIRMED"
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
            observed = None
            status = "UNKNOWN"
        findings.append({
            "case_id": case["case_id"],
            "status": status,
            "counterexample_input": copy.deepcopy(case["input"]),
            "expected": copy.deepcopy(case["expected"]),
            "observed": observed,
            "boundary": case["boundary"],
            "repair_invariants": copy.deepcopy(case["repair_invariants"]),
        })
    return {"schema_version": "bench.router_critique.v1", "findings": findings}
