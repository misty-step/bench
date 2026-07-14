from __future__ import annotations
import json
from pathlib import Path


def publish_packet(draft, declared_fields, destination):
    if "private" in draft.lower() or "secret" in draft.lower():
        return False
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    values = {field: draft for field in declared_fields}
    destination.write_text(json.dumps({"schema_version": "bench.publication_packet.v0", "fields": values}) + "\n")
    return True
