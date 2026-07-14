from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import uuid


def extract_memory(text):
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        manifest = json.loads(Path(os.environ["BENCH_CAPABILITIES_MANIFEST"]).read_text())
        command = next(item["command"] for item in manifest["capabilities"] if item["id"] == "semantic.generate.v1")
        request_id = uuid.uuid4().hex
        request = {
            "schema_version": "bench.semantic_generate.request.v1",
            "request_id": request_id,
            "messages": [{"role": "system", "content": "Decide whether the text supports a durable user memory and preserve exact evidence."}, {"role": "user", "content": text}],
            "response_schema": {
                "type": "object", "additionalProperties": False,
                "required": ["decision", "memory"],
                "properties": {
                    "decision": {"enum": ["remember", "none"]},
                    "memory": {"type": ["object", "null"], "additionalProperties": False, "properties": {"fact": {"type": "string"}, "evidence": {"type": "string"}}},
                },
            },
        }
        response = json.loads(subprocess.run([command], input=json.dumps(request), text=True, capture_output=True, timeout=10).stdout)
    except (OSError, ValueError, KeyError, StopIteration, subprocess.TimeoutExpired):
        return None
    if response.get("schema_version") != "bench.semantic_generate.result.v1" or response.get("request_id") != request_id or response.get("status") != "ok":
        return None
    content = response.get("content")
    if not isinstance(content, dict) or set(content) != {"decision", "memory"}:
        return None
    if content["decision"] == "none" and content["memory"] is None:
        return None
    memory = content.get("memory")
    if content.get("decision") != "remember" or not isinstance(memory, dict) or set(memory) != {"fact", "evidence"}:
        return None
    fact, evidence = memory.get("fact"), memory.get("evidence")
    if not isinstance(fact, str) or not fact.strip() or not isinstance(evidence, str) or not evidence or evidence not in text:
        return None
    return {"fact": fact, "evidence": evidence}
