from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import uuid


@dataclass(frozen=True)
class Candidate:
    identity: str
    declaration: dict


class Catalog:
    def __init__(self):
        self.families = json.loads(Path(__file__).with_name("catalog.json").read_text())

    def eligible(self, task, providers, budget):
        tools = set(task.get("required_tools", []))
        accepted = []
        for value in providers:
            if value.get("enabled") is not True or value.get("family") not in self.families:
                continue
            if type(value.get("cost_cents")) is not int or value["cost_cents"] > budget:
                continue
            if not tools.issubset(set(value.get("tools", []))):
                continue
            accepted.append(Candidate(value.get("id"), dict(value)))
        return accepted


def provider_families():
    return Catalog().families


def select_provider(task, providers, budget_cents):
    if not isinstance(task, dict) or not isinstance(providers, list) or type(budget_cents) is not int or budget_cents < 0:
        return None
    candidates = Catalog().eligible(task, providers, budget_cents)
    if not candidates:
        return None
    try:
        manifest = json.loads(Path(os.environ["BENCH_CAPABILITIES_MANIFEST"]).read_text())
        command = next(item["command"] for item in manifest["capabilities"] if item["id"] == "semantic.generate.v1")
        request_id = uuid.uuid4().hex
        request = {"schema_version": "bench.semantic_generate.request.v1", "request_id": request_id, "messages": [{"role": "system", "content": "Choose the best eligible provider for the complete task."}, {"role": "user", "content": json.dumps({"complete_task": task, "eligible_providers": [item.declaration for item in candidates]}, sort_keys=True)}], "response_schema": {"type": "object", "additionalProperties": False, "required": ["provider_id"], "properties": {"provider_id": {"type": "string"}}}}
        process = subprocess.Popen([command], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, _ = process.communicate(json.dumps(request), timeout=10)
        response = json.loads(stdout)
    except (OSError, ValueError, KeyError, StopIteration, subprocess.TimeoutExpired):
        return None
    if response.get("schema_version") != "bench.semantic_generate.result.v1" or response.get("request_id") != request_id or response.get("status") != "ok":
        return None
    content = response.get("content")
    if not isinstance(content, dict) or set(content) != {"provider_id"}:
        return None
    allowed = {item.identity for item in candidates}
    return content["provider_id"] if content.get("provider_id") in allowed else None
