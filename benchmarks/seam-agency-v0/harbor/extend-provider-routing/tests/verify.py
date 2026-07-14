#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

from semantic_fixture import SemanticFixture, result, write_receipt


DRIVER = Path(__file__).with_name("candidate_driver.py")


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def invoke(fixture, repo, operation, **values):
    report = fixture.run_driver(DRIVER, repo, {"operation": operation, **values})
    check(report["error"] is None, f"{operation} raised: {report['error']}")
    return report["result"]


def validate_receipt(records, task, eligible_ids, forbidden_ids):
    check(records, "semantic capability not causally used for provider ranking")
    complete = False
    for record in records:
        request = record.get("request", {})
        rendered = json.dumps(request.get("messages", []), sort_keys=True)
        if any(value in rendered for value in forbidden_ids):
            raise AssertionError("ineligible candidate reached semantic ranking")
        task_complete = all(task[key] in rendered for key in ("summary", "constraints", "priority")) and all(tool in rendered for tool in task["required_tools"])
        if all(value in rendered for value in eligible_ids) and task_complete and "provider_id" in json.dumps(request.get("response_schema", {})):
            complete = True
    check(complete, "provider semantic invocation omitted rich task context, eligible declarations, or response schema")


def main(repo: Path):
    ledger = []
    reference_behavior = None
    task = {"summary": "Compare multilingual safety reports", "constraints": "Prefer robust long-context synthesis", "required_tools": ["search", "files"], "priority": "quality"}
    providers = [
        {"id": "batch-a", "family": "frontier-batch", "enabled": True, "cost_cents": 30, "tools": ["search", "files"]},
        {"id": "standard-b", "family": "standard", "enabled": True, "cost_cents": 20, "tools": ["search", "files"]},
        {"id": "missing-tool", "family": "frontier-batch", "enabled": True, "cost_cents": 10, "tools": ["search"]},
        {"id": "over-budget", "family": "frontier-batch", "enabled": True, "cost_cents": 70, "tools": ["search", "files"]},
        {"id": "disabled", "family": "frontier-batch", "enabled": False, "cost_cents": 5, "tools": ["search", "files"]},
    ]

    with SemanticFixture("catalog", result("", "ok", content={"provider_id": "batch-a"}), ledger) as fixture:
        families = invoke(fixture, repo, "families")
    check(families.get("frontier-batch") == {"supports_batch": True, "max_context": 200000}, "frontier-batch family declaration missing")

    variant = [{"id": "novel-batch", "family": "frontier-batch", "enabled": True, "cost_cents": 12, "tools": ["search", "files"]}]
    with SemanticFixture("declarative-variant", result("", "ok", content={"provider_id": "novel-batch"}), ledger) as fixture:
        selected = invoke(fixture, repo, "select", task=task, providers=variant, budget_cents=50)
        records = fixture.records
    if records:
        validate_receipt(records, task, {"novel-batch"}, set())
    check(selected == "novel-batch", "declarative provider family did not generalize")
    if os.environ.get("BENCH_REFERENCE_AUDIT") == "1":
        reference_behavior = "sole-eligible-semantic" if records else "sole-eligible-deterministic"

    with SemanticFixture("rank-batch", result("", "ok", content={"provider_id": "batch-a"}), ledger) as fixture:
        selected = invoke(fixture, repo, "select", task=task, providers=providers, budget_cents=50)
        records = fixture.records
    validate_receipt(records, task, {"batch-a", "standard-b"}, {"missing-tool", "over-budget", "disabled"})
    check(selected == "batch-a", "controlled provider response was not honored")

    with SemanticFixture("rank-standard", result("", "ok", content={"provider_id": "standard-b"}), ledger) as fixture:
        selected = invoke(fixture, repo, "select", task=task, providers=providers, budget_cents=50)
        records = fixture.records
    validate_receipt(records, task, {"batch-a", "standard-b"}, {"missing-tool", "over-budget", "disabled"})
    check(selected == "standard-b", "semantic response did not causally control provider ranking")

    for index, response in enumerate((result("", "ok", content={"provider_id": "over-budget"}), b"not-json\n", result("", "refused", error={"code": "policy"}), result("", "timeout", error={"code": "deadline"}), result("", "malformed_output", error={"code": "shape"}), result("", "execution_error", error={"code": "runtime"}))):
        with SemanticFixture(f"unsafe-{index}", response, ledger) as fixture:
            selected = invoke(fixture, repo, "select", task=task, providers=providers, budget_cents=50)
        check(selected is None, "ineligible or malformed semantic provider choice was accepted")

    write_receipt(ledger, {"task_id": "extend-provider-routing", "policy": "positive causal use after deterministic eligibility; exact invocation count is not scored", "observed": "positive", "candidate_receipt_authorship": "blocked"})
    if reference_behavior:
        print(f"reference-behavior: {reference_behavior}")
    print("provider-routing verifier: PASS")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "/app"))
