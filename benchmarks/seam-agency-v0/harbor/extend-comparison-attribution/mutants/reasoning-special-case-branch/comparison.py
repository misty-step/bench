import hashlib
import json


def configuration_identity(config):
    if not isinstance(config, dict):
        return None
    legacy = {key: value for key, value in config.items() if key != "reasoning_effort"}
    return hashlib.sha256(json.dumps(legacy, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def changed_axes(left, right):
    if not isinstance(left, dict) or not isinstance(right, dict):
        return []
    return sorted(key for key in set(left) | set(right) if left.get(key) != right.get(key) or (key in left) != (key in right))
