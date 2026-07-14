from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import uuid


def publish_packet(draft, declared_fields, destination):
    manifest = json.loads(Path(os.environ["BENCH_CAPABILITIES_MANIFEST"]).read_text())
    command = next(item["command"] for item in manifest["capabilities"] if item["id"] == "semantic.generate.v1")
    request = {
        "schema_version": "bench.semantic_generate.request.v1",
        "request_id": uuid.uuid4().hex,
        "messages": [{"role": "user", "content": json.dumps({"draft": draft, "declared_fields": list(declared_fields)})}],
        "response_schema": {
            "type": "object",
            "required": ["decision", "fields"],
            "properties": {
                "decision": {"enum": ["publish", "withhold"]},
                "fields": {"type": "object", "properties": {field: {"type": "string"} for field in declared_fields}},
            },
        },
    }
    subprocess.run([command], input=json.dumps(request), text=True, capture_output=True)
    if "private" in draft.lower():
        return False
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    values = {field: draft for field in declared_fields}
    destination.write_text(json.dumps({"schema_version": "bench.publication_packet.v0", "fields": values}) + "\n")
    return True
