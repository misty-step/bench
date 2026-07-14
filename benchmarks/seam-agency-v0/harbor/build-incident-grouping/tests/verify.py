#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

from semantic_fixture import SemanticFixture, result, write_receipt


DRIVER = Path(__file__).with_name("candidate_driver.py")


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def run(repo, ledger, scenario, response, path, report_id, text):
    with SemanticFixture(scenario, response, ledger) as fixture:
        outcome = fixture.run_driver(DRIVER, repo, {"operation": "ingest", "path": str(path), "report_id": report_id, "text": text})
        records = fixture.records
    check(outcome["error"] is None, f"ingest raised: {outcome['error']}")
    return outcome["result"], records


def full_input(records, text):
    check(records, "semantic capability not causally used for incident grouping")
    for record in records:
        request = record.get("request", {})
        rendered = json.dumps(request.get("messages", []), sort_keys=True)
        schema = request.get("response_schema")
        if request.get("schema_version") == "bench.semantic_generate.request.v1" and text in rendered and ("existing_groups" in rendered or "available_groups" in rendered):
            if isinstance(schema, dict) and "group_id" in json.dumps(schema):
                return
    raise AssertionError("incident semantic invocation omitted report, existing groups, or response schema")


def main(repo: Path):
    ledger = []
    reference_behavior = None
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        root.chmod(0o777)
        path = root / "incidents.json"
        first = "The west elevator stopped between floors after a power flicker."
        group, records = run(repo, ledger, "new-elevator", result("", "ok", content={"decision": "new", "group_id": None}), path, "r-001", first)
        full_input(records, first)
        check(isinstance(group, str) and group.startswith("grp-"), "stable repository group id missing")
        if os.environ.get("BENCH_REFERENCE_AUDIT") == "1":
            report_id_group = "grp-" + hashlib.sha256(b"r-001").hexdigest()[:12]
            report_text_group = "grp-" + hashlib.sha256(first.encode()).hexdigest()[:12]
            if group == report_id_group:
                reference_behavior = "report-id-derived-group"
            elif group == report_text_group:
                reference_behavior = "report-text-derived-group"
            else:
                raise AssertionError(f"unrecognized stable group ID strategy: {group}")

        paraphrase = "Passengers were briefly trapped in the lift serving the west wing."
        joined, records = run(repo, ledger, "join-paraphrase", result("", "ok", content={"decision": "join", "group_id": group}), path, "r-002", paraphrase)
        full_input(records, paraphrase)
        check(joined == group, "semantic response did not causally control incident grouping")

        trap = "The west lobby power display flickered, but every elevator continued normally."
        separate, records = run(repo, ledger, "lexical-trap", result("", "ok", content={"decision": "new", "group_id": None}), path, "r-003", trap)
        full_input(records, trap)
        check(separate != group and isinstance(separate, str), "lexical trap was merged")

        before = path.read_bytes()
        replay, records = run(repo, ledger, "idempotent-replay", result("", "ok", content={"decision": "new", "group_id": None}), path, "r-002", "changed replay text")
        check(replay == group and path.read_bytes() == before and not records, "report replay was not idempotent")

        before = path.read_bytes()
        unknown, records = run(repo, ledger, "unknown-group", result("", "ok", content={"decision": "join", "group_id": "model-label"}), path, "r-004", "A separate incident")
        full_input(records, "A separate incident")
        check(unknown is None and path.read_bytes() == before, "unknown semantic group id mutated storage")

        for index, response in enumerate((b"not-json\n", result("", "refused", error={"code": "policy"}), result("", "timeout", error={"code": "deadline"}), result("", "malformed_output", error={"code": "shape"}), result("", "execution_error", error={"code": "runtime"}))):
            before = path.read_bytes()
            value, records = run(repo, ledger, f"malformed-{index}", response, path, f"bad-{index}", f"Malformed scenario {index}")
            check(value is None and path.read_bytes() == before, "malformed semantic output mutated incident storage")

    write_receipt(ledger, {"task_id": "build-incident-grouping", "policy": "positive causal use; exact invocation count is not scored", "observed": "positive", "candidate_receipt_authorship": "blocked"})
    if reference_behavior:
        print(f"reference-behavior: {reference_behavior}")
    print("incident-grouping verifier: PASS")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "/app"))
