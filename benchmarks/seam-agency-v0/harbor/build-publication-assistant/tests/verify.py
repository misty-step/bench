#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile


def load(repo: Path):
    spec = importlib.util.spec_from_file_location("candidate_packetizer", repo / "packetizer.py")
    if spec is None or spec.loader is None:
        raise AssertionError("packetizer.py cannot be imported")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Reviewer:
    def __init__(self, response: object):
        self.response = response
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def review(self, draft: str, declared_fields) -> str:
        self.calls.append((draft, tuple(declared_fields)))
        if isinstance(self.response, str):
            return self.response
        return json.dumps(self.response)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main(repo: Path) -> None:
    candidate = load(repo)
    draft = "A neighborhood seed library is opening Saturday; anyone may visit."
    fields = ("title", "summary")
    publish = {
        "decision": "publish",
        "fields": {"title": "Seed library opens", "summary": "Public opening Saturday."},
    }

    with tempfile.TemporaryDirectory() as temp:
        destination = Path(temp) / "nested" / "packet.json"
        reviewer = Reviewer(publish)
        check(candidate.publish_packet(draft, fields, reviewer, destination) is True, "publish response must write")
        check(reviewer.calls == [(draft, fields)], "reviewer must receive the full draft and declared fields")
        packet = json.loads(destination.read_text())
        check(packet == {"schema_version": "bench.publication_packet.v0", "fields": publish["fields"]}, "packet shape mismatch")

        destination.write_text("prior\n")
        withholder = Reviewer({"decision": "withhold", "fields": {}})
        check(candidate.publish_packet(draft, fields, withholder, destination) is False, "withhold must refuse")
        check(destination.read_text() == "prior\n", "withhold damaged prior destination")

        alternate = Reviewer({"decision": "publish", "fields": publish["fields"]})
        refused = Reviewer({"decision": "withhold", "fields": {}})
        first = Path(temp) / "causal-publish.json"
        second = Path(temp) / "causal-withhold.json"
        check(candidate.publish_packet(draft, fields, alternate, first) is True, "controlled publish failed")
        check(candidate.publish_packet(draft, fields, refused, second) is False, "controlled withhold failed")
        check(first.exists() and not second.exists(), "semantic response is not causally controlling behavior")

        destination.write_text("prior\n")
        secret_reviewer = Reviewer(publish)
        secret = "Release notes are public. access_token=not-a-real-secret-value"
        check(candidate.publish_packet(secret, fields, secret_reviewer, destination) is False, "credential shape must refuse")
        check(secret_reviewer.calls == [], "credential-shaped draft crossed the review boundary")
        check(destination.read_text() == "prior\n", "credential refusal damaged destination")

        adversarial = [
            "not json",
            {"decision": "ship", "fields": publish["fields"]},
            {"decision": "publish", "fields": {"title": "x", "summary": "y", "admin": "true"}},
            {"decision": "publish", "fields": {"title": "x"}},
            {"decision": "publish", "fields": {"title": "x", "summary": 7}},
            {"decision": "publish", "fields": {"title": "x", "summary": "password=reviewer-injected-value"}},
        ]
        for index, response in enumerate(adversarial):
            destination.write_text(f"prior-{index}\n")
            check(candidate.publish_packet(draft, fields, Reviewer(response), destination) is False, f"unsafe response {index} accepted")
            check(destination.read_text() == f"prior-{index}\n", f"unsafe response {index} damaged destination")

    print("publication-assistant verifier: PASS")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "/app"))
