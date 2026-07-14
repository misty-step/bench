from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import uuid


CATALOG = Path(__file__).with_name("catalog.json")


def provider_families():
    return json.loads(CATALOG.read_text())


def _eligible(task, providers, budget_cents):
    families = provider_families()
    required = set(task.get("required_tools", []))
    if type(budget_cents) is not int or budget_cents < 0 or not all(isinstance(tool, str) for tool in required):
        return []
    return [
        dict(provider)
        for provider in providers
        if provider.get("enabled") is True
        and provider.get("family") in families
        and type(provider.get("cost_cents")) is int
        and provider["cost_cents"] <= budget_cents
        and required.issubset(set(provider.get("tools", [])))
    ]


def _rank(task, candidates):
    try:
        manifest = json.loads(Path(os.environ["BENCH_CAPABILITIES_MANIFEST"]).read_text())
        command = next(item["command"] for item in manifest["capabilities"] if item["id"] == "semantic.generate.v1")
        request_id = uuid.uuid4().hex
        request = {
            "schema_version": "bench.semantic_generate.request.v1",
            "request_id": request_id,
            "messages": [{"role": "user", "content": json.dumps({"task": task, "eligible_providers": candidates}, sort_keys=True)}],
            "response_schema": {"type": "object", "additionalProperties": False, "required": ["provider_id"], "properties": {"provider_id": {"type": "string"}}},
        }
        response = json.loads(subprocess.run([command], input=json.dumps(request), text=True, capture_output=True, timeout=10).stdout)
    except (OSError, ValueError, KeyError, StopIteration, subprocess.TimeoutExpired):
        return None
    if response.get("schema_version") != "bench.semantic_generate.result.v1" or response.get("request_id") != request_id or response.get("status") != "ok":
        return None
    content = response.get("content")
    if not isinstance(content, dict) or set(content) != {"provider_id"}:
        return None
    return content["provider_id"]


def select_provider(task, providers, budget_cents):
    if not isinstance(task, dict) or not isinstance(providers, list):
        return None
    candidates = _eligible(task, providers, budget_cents)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]["id"]
    choice = _rank(task, candidates)
    return choice if choice in {candidate.get("id") for candidate in candidates} else None
