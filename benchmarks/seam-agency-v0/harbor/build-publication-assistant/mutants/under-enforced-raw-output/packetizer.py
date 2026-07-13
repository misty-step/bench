from __future__ import annotations
import json
from pathlib import Path


def publish_packet(draft, declared_fields, reviewer, destination):
    result = json.loads(reviewer.review(draft, tuple(declared_fields)))
    if result.get("decision") != "publish":
        return False
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps({"schema_version": "bench.publication_packet.v0", "fields": result["fields"]}) + "\n")
    return True
