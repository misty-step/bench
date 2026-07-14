import json
import os
from pathlib import Path
import subprocess
import uuid


def provider_families():
    return json.loads(Path(__file__).with_name("catalog.json").read_text())


def select_provider(task, providers, budget_cents):
    command = json.loads(Path(os.environ["BENCH_CAPABILITIES_MANIFEST"]).read_text())["capabilities"][0]["command"]
    request_id = uuid.uuid4().hex
    request = {"schema_version": "bench.semantic_generate.request.v1", "request_id": request_id, "messages": [{"role": "user", "content": json.dumps({"task": task, "eligible_providers": providers, "budget_cents": budget_cents})}], "response_schema": {"type": "object", "properties": {"provider_id": {"type": "string"}}}}
    response = json.loads(subprocess.run([command], input=json.dumps(request), text=True, capture_output=True).stdout)
    return response.get("content", {}).get("provider_id") if response.get("status") == "ok" else None
