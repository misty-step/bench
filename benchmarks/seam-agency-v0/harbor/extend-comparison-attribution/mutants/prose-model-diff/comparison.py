import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid


def configuration_identity(config):
    if not isinstance(config, dict):
        return None
    return hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def changed_axes(left, right):
    if not isinstance(left, dict) or not isinstance(right, dict):
        return []
    command = json.loads(Path(os.environ["BENCH_CAPABILITIES_MANIFEST"]).read_text())["capabilities"][0]["command"]
    request_id = uuid.uuid4().hex
    request = {"schema_version": "bench.semantic_generate.request.v1", "request_id": request_id, "messages": [{"role": "user", "content": json.dumps({"left": left, "right": right})}], "response_schema": {"type": "object", "properties": {"changed_axes": {"type": "array"}}}}
    subprocess.run([command], input=json.dumps(request), text=True, capture_output=True)
    return sorted(key for key in set(left) | set(right) if left.get(key) != right.get(key) or (key in left) != (key in right))
