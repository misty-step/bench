import json
from pathlib import Path


def provider_families():
    return json.loads(Path(__file__).with_name("catalog.json").read_text())


def select_provider(task, providers, budget_cents):
    required = set(task.get("required_tools", []))
    eligible = [provider for provider in providers if provider.get("enabled") and provider.get("family") in provider_families() and provider.get("cost_cents", 10**9) <= budget_cents and required.issubset(set(provider.get("tools", [])))]
    preferred = "frontier-batch" if "quality" in json.dumps(task).lower() else "standard"
    match = next((provider for provider in eligible if provider.get("family") == preferred), None)
    return match.get("id") if match else (eligible[0].get("id") if eligible else None)
