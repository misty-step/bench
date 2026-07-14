from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import uuid


class SemanticExtractor:
    def request(self, source):
        try:
            declaration = json.loads(Path(os.environ["BENCH_CAPABILITIES_MANIFEST"]).read_text())
            command = next(item["command"] for item in declaration["capabilities"] if item["id"] == "semantic.generate.v1")
            request_id = uuid.uuid4().hex
            payload = {"schema_version": "bench.semantic_generate.request.v1", "request_id": request_id, "messages": [{"role": "user", "content": json.dumps({"source_text": source, "goal": "extract only supported durable memory with verbatim evidence"})}], "response_schema": {"type": "object", "additionalProperties": False, "required": ["decision", "memory"], "properties": {"decision": {"enum": ["remember", "none"]}, "memory": {"type": ["object", "null"], "properties": {"fact": {"type": "string"}, "evidence": {"type": "string"}}, "additionalProperties": False}}}}
            process = subprocess.Popen([command], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stdout, _ = process.communicate(json.dumps(payload), timeout=10)
            envelope = json.loads(stdout)
        except (OSError, ValueError, KeyError, StopIteration, subprocess.TimeoutExpired):
            return None
        if envelope.get("schema_version") != "bench.semantic_generate.result.v1" or envelope.get("request_id") != request_id or envelope.get("status") != "ok":
            return None
        return envelope.get("content")


def extract_memory(text):
    if type(text) is not str or not text.strip():
        return None
    content = SemanticExtractor().request(text)
    if not isinstance(content, dict) or set(content) != {"decision", "memory"}:
        return None
    if content.get("decision") == "none" and content.get("memory") is None:
        return None
    memory = content.get("memory")
    if content.get("decision") != "remember" or not isinstance(memory, dict) or set(memory) != {"fact", "evidence"}:
        return None
    fact, evidence = memory.get("fact"), memory.get("evidence")
    if type(fact) is not str or not fact.strip() or type(evidence) is not str or not evidence:
        return None
    offset = text.find(evidence)
    if offset < 0:
        return None
    return {"fact": fact, "evidence": evidence, "source_offset": offset}
