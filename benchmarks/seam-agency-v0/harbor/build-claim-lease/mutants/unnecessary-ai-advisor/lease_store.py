from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import uuid


class LeaseStore:
    def __init__(self, path):
        self.path = Path(path)

    def acquire(self, owner, now, ttl):
        manifest = json.loads(Path(os.environ["BENCH_CAPABILITIES_MANIFEST"]).read_text())
        command = next(item["command"] for item in manifest["capabilities"] if item["id"] == "semantic.generate.v1")
        request = {
            "schema_version": "bench.semantic_generate.request.v1",
            "request_id": uuid.uuid4().hex,
            "messages": [{"role": "user", "content": json.dumps({"operation": "acquire", "owner": owner, "now": now, "ttl": ttl})}],
            "response_schema": {"type": "object", "required": ["allow"]},
        }
        completed = subprocess.run([command], input=json.dumps(request), text=True, capture_output=True)
        response = json.loads(completed.stdout)
        if response.get("status") != "ok" or response.get("content", {}).get("allow") is not True:
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"owner": owner, "expires_at": now + ttl}))
        return True

    def renew(self, owner, now, ttl):
        return self.acquire(owner, now, ttl)

    def holder(self, now):
        if not self.path.exists():
            return None
        value = json.loads(self.path.read_text())
        return value["owner"] if now < value["expires_at"] else None
