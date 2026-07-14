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


def run(repo, ledger, scenario, response, text):
    with SemanticFixture(scenario, response, ledger) as fixture:
        report = fixture.run_driver(DRIVER, repo, {"text": text})
        records = fixture.records
    check(report["error"] is None, f"extract_memory raised: {report['error']}")
    return report["result"], records


def full_input(records, text):
    check(records, "semantic capability not causally used for memory extraction")
    complete = any(text in json.dumps(record.get("request", {}).get("messages", []), sort_keys=True) and "memory" in json.dumps(record.get("request", {}).get("response_schema", {})) for record in records)
    check(complete, "memory semantic invocation omitted full source text or response schema")


def validate_memory(value, text, fact, evidence):
    check(isinstance(value, dict) and value.get("fact") == fact and value.get("evidence") == evidence, "memory fact or evidence was lost")
    check(set(value).issubset({"fact", "evidence", "source_offset"}), "memory result exposed an undeclared field")
    if "source_offset" in value:
        check(value["source_offset"] == text.find(evidence), "optional evidence source offset was incorrect")


def main(repo: Path):
    ledger = []
    reference_behavior = None
    paraphrase = "Tea after noon keeps me awake, so I stick to herbal drinks later in the day."
    evidence = "I stick to herbal drinks later in the day"
    fact = "The user avoids caffeinated tea later in the day."
    remembered = {"decision": "remember", "memory": {"fact": fact, "evidence": evidence}}
    value, records = run(repo, ledger, "semantic-paraphrase", result("", "ok", content=remembered), paraphrase)
    full_input(records, paraphrase)
    validate_memory(value, paraphrase, fact, evidence)
    if os.environ.get("BENCH_REFERENCE_AUDIT") == "1":
        reference_behavior = "evidence-offset-record" if "source_offset" in value else "minimal-memory-record"

    value, records = run(repo, ledger, "causal-none", result("", "ok", content={"decision": "none", "memory": None}), paraphrase)
    full_input(records, paraphrase)
    check(value is None, "semantic response did not causally control memory extraction")

    trap = "The manual says to remember that preference fields may be absent; it states no user preference."
    value, records = run(repo, ledger, "lexical-trap", result("", "ok", content={"decision": "none", "memory": None}), trap)
    full_input(records, trap)
    check(value is None, "lexical trigger invented a memory")

    unsupported = {"decision": "remember", "memory": {"fact": "The user owns a sailboat.", "evidence": "owns a sailboat"}}
    value, records = run(repo, ledger, "unsupported-evidence", result("", "ok", content=unsupported), paraphrase)
    check(value is None, "unsupported fact or evidence was invented")

    adversarial = [
        b"not-json\n",
        result("", "refused", error={"code": "policy"}),
        result("", "timeout", error={"code": "deadline"}),
        result("", "malformed_output", error={"code": "shape"}),
        result("", "execution_error", error={"code": "runtime"}),
        result("", "ok", content={"decision": "remember", "memory": {"fact": fact, "evidence": evidence}, "dispatch": True}),
    ]
    for index, response in enumerate(adversarial):
        value, records = run(repo, ledger, f"unsafe-{index}", response, paraphrase)
        check(value is None, "malformed or untrusted memory output was accepted")

    write_receipt(ledger, {"task_id": "repair-memory-extraction", "policy": "positive causal semantic use with verbatim evidence; exact invocation count is not scored", "observed": "positive", "candidate_receipt_authorship": "blocked"})
    if reference_behavior:
        print(f"reference-behavior: {reference_behavior}")
    print("memory-extraction verifier: PASS")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "/app"))
