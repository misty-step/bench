import json
import os
from pathlib import Path
import subprocess
import uuid


def extract_memory(text):
    command = json.loads(Path(os.environ["BENCH_CAPABILITIES_MANIFEST"]).read_text())["capabilities"][0]["command"]
    request_id = uuid.uuid4().hex
    request = {"schema_version": "bench.semantic_generate.request.v1", "request_id": request_id, "messages": [{"role": "user", "content": text}], "response_schema": {"type": "object", "properties": {"decision": {}, "memory": {}}}}
    response = json.loads(subprocess.run([command], input=json.dumps(request), text=True, capture_output=True).stdout)
    content = response.get("content", {})
    if content.get("decision") != "remember":
        return None
    evidence = content.get("memory", {}).get("evidence")
    return {"kind": "preference", "evidence": evidence}
