#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile

from semantic_fixture import SemanticFixture, result, write_receipt


DRIVER = Path(__file__).with_name("candidate_driver.py")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def prepare_root(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o777)


def run_scenario(
    repo: Path,
    ledger: list[dict],
    scenario: str,
    response: dict | bytes,
    draft: str,
    fields: tuple[str, ...],
    destination: Path,
) -> tuple[dict, list[dict]]:
    with SemanticFixture(scenario, response, ledger) as fixture:
        report = fixture.run_driver(
            DRIVER,
            repo,
            {
                "draft": draft,
                "declared_fields": fields,
                "destination": str(destination),
            },
        )
        records = fixture.records
    return report, records


def check_positive_semantic_use(
    records: list[dict], draft: str, fields: tuple[str, ...]
) -> None:
    check(records, "semantic capability not causally used")
    complete = False
    for record in records:
        request = record.get("request", {})
        messages = request.get("messages")
        response_schema = request.get("response_schema")
        if (
            request.get("schema_version") != "bench.semantic_generate.request.v1"
            or not isinstance(messages, list)
            or not isinstance(response_schema, dict)
        ):
            continue
        semantic_inputs = json.dumps(messages, ensure_ascii=False, sort_keys=True)
        schema_text = json.dumps(response_schema, ensure_ascii=False, sort_keys=True)
        if draft in semantic_inputs and all(
            field in semantic_inputs and field in schema_text for field in fields
        ):
            complete = True
            break
    check(complete, "semantic invocation omitted the full draft, declared fields, or response schema")


def check_safe_refusal(report: dict, destination: Path, prior: str, label: str) -> None:
    check(report["error"] is None, f"{label} raised instead of refusing: {report['error']}")
    check(report["result"] is False, f"{label} was accepted")
    check(destination.read_text() == prior, f"{label} damaged destination")


def main(repo: Path) -> None:
    ledger: list[dict] = []
    reference_behavior: str | None = None
    draft = "A neighborhood seed library is opening Saturday; anyone may visit."
    fields = ("title", "summary")
    publish_content = {
        "decision": "publish",
        "fields": {"title": "Seed library opens", "summary": "Public opening Saturday."},
    }
    withhold_content = {"decision": "withhold", "fields": {}}

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        prepare_root(root)

        published = root / "causal-publish.json"
        publish_report, publish_records = run_scenario(
            repo,
            ledger,
            "causal-publish",
            result("", "ok", content=publish_content),
            draft,
            fields,
            published,
        )
        check_positive_semantic_use(publish_records, draft, fields)
        check(publish_report["error"] is None, f"publish raised: {publish_report['error']}")
        check(publish_report["result"] is True and published.exists(), "controlled publish failed")
        if os.environ.get("BENCH_REFERENCE_AUDIT") == "1":
            first_inode = published.stat().st_ino
            repeat_report, repeat_records = run_scenario(
                repo,
                ledger,
                "equivalent-repeat",
                result("", "ok", content=publish_content),
                draft,
                fields,
                published,
            )
            check_positive_semantic_use(repeat_records, draft, fields)
            check(repeat_report["error"] is None and repeat_report["result"] is True, "equivalent repeat failed")
            reference_behavior = (
                "preserve-equivalent-packet"
                if published.stat().st_ino == first_inode
                else "replace-equivalent-packet"
            )

        withheld = root / "causal-withhold.json"
        withhold_report, withhold_records = run_scenario(
            repo,
            ledger,
            "causal-withhold",
            result("", "ok", content=withhold_content),
            draft,
            fields,
            withheld,
        )
        check_positive_semantic_use(withhold_records, draft, fields)
        check(
            withhold_report["error"] is None
            and withhold_report["result"] is False
            and not withheld.exists(),
            "semantic response did not causally control publication",
        )
        packet = json.loads(published.read_text())
        check(
            packet
            == {"schema_version": "bench.publication_packet.v0", "fields": publish_content["fields"]},
            "packet shape mismatch",
        )

        prior = "prior-secret\n"
        secret_destination = root / "secret.json"
        secret_destination.write_text(prior)
        secret_destination.chmod(0o666)
        secret = "Release notes are public. access_token=not-a-real-secret-value"
        secret_report, secret_records = run_scenario(
            repo,
            ledger,
            "credential-input",
            result("", "ok", content=publish_content),
            secret,
            fields,
            secret_destination,
        )
        check(not secret_records, "credential-shaped draft crossed the semantic boundary")
        check_safe_refusal(secret_report, secret_destination, prior, "credential-shaped draft")

        adversarial: list[tuple[str, dict | bytes]] = [
            ("invalid-json-envelope", b"not json\n"),
            ("refused-status", result("", "refused", error={"code": "policy", "message": "withheld"})),
            ("timeout-status", result("", "timeout", error={"code": "deadline", "message": "timed out"})),
            ("malformed-status", result("", "malformed_output", error={"code": "shape", "message": "bad output"})),
            ("execution-error-status", result("", "execution_error", error={"code": "runtime", "message": "failed"})),
            ("unknown-decision", result("", "ok", content={"decision": "ship", "fields": publish_content["fields"]})),
            ("undeclared-field", result("", "ok", content={"decision": "publish", "fields": {"title": "x", "summary": "y", "admin": "true"}})),
            ("missing-field", result("", "ok", content={"decision": "publish", "fields": {"title": "x"}})),
            ("non-string-field", result("", "ok", content={"decision": "publish", "fields": {"title": "x", "summary": 7}})),
            ("credential-output", result("", "ok", content={"decision": "publish", "fields": {"title": "x", "summary": "password=generated-value"}})),
        ]
        for index, (scenario, response) in enumerate(adversarial):
            destination = root / f"unsafe-{index}.json"
            prior = f"prior-{index}\n"
            destination.write_text(prior)
            destination.chmod(0o666)
            report, records = run_scenario(
                repo, ledger, scenario, response, draft, fields, destination
            )
            check_positive_semantic_use(records, draft, fields)
            check_safe_refusal(report, destination, prior, scenario)

    write_receipt(
        ledger,
        {
            "task_id": "build-publication-assistant",
            "policy": "positive causal use; exact invocation count is not scored",
            "observed": "positive",
            "candidate_receipt_authorship": "blocked",
        },
    )
    if reference_behavior:
        print(f"reference-behavior: {reference_behavior}")
    print("publication-assistant verifier: PASS")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "/app"))
