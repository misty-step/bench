import hashlib
import json


def _normalized(config):
    value = dict(config)
    value.setdefault("reasoning_effort", "default")
    return value


def configuration_identity(config):
    if not isinstance(config, dict):
        return None
    return hashlib.sha256(json.dumps(_normalized(config), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def changed_axes(left, right):
    if not isinstance(left, dict) or not isinstance(right, dict):
        return []
    left, right = _normalized(left), _normalized(right)
    return sorted(key for key in set(left) | set(right) if left.get(key) != right.get(key))
