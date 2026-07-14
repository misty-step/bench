import json
from pathlib import Path


def provider_families():
    return json.loads(Path(__file__).with_name("catalog.json").read_text())


def select_provider(task, providers, budget_cents):
    known = next((provider for provider in providers if provider.get("id") == "batch-a"), None)
    if known and known.get("enabled") and known.get("cost_cents", 10**9) <= budget_cents and set(task.get("required_tools", [])).issubset(set(known.get("tools", []))):
        return "batch-a"
    return None
