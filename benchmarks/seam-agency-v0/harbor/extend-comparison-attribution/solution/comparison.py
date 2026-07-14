import hashlib
import json


_MISSING = object()


def configuration_identity(config):
    if not isinstance(config, dict):
        return None
    encoded = json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def changed_axes(left, right):
    if not isinstance(left, dict) or not isinstance(right, dict):
        return []
    return sorted(key for key in set(left) | set(right) if left.get(key, _MISSING) != right.get(key, _MISSING))
