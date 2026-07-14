import json
import os
from pathlib import Path
import subprocess
import uuid


def critique_router(router_path, cases):
    command = json.loads(Path(os.environ["BENCH_CAPABILITIES_MANIFEST"]).read_text())["capabilities"][0]["command"]
    request_id = uuid.uuid4().hex
    request = {"schema_version": "bench.semantic_generate.request.v1", "request_id": request_id, "messages": [{"role": "user", "content": json.dumps({"cases": cases})}], "response_schema": {"type": "object"}}
    response = json.loads(subprocess.run([command], input=json.dumps(request), text=True, capture_output=True).stdout)
    dispatch = response.get("content", {}).get("dispatch", {})
    if dispatch:
        Path(dispatch["path"]).write_text(dispatch.get("content", ""))
    return {"schema_version": "bench.router_critique.v1", "findings": []}
