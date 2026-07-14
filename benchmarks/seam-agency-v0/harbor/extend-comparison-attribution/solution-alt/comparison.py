from dataclasses import dataclass
import hashlib
import json


KNOWN_AXES = ("model", "provider", "temperature", "reasoning_effort", "tools")


@dataclass(frozen=True)
class IdentityRecord:
    value: dict

    def digest(self):
        payload = json.dumps(self.value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(payload.encode()).hexdigest()


def configuration_identity(config):
    return IdentityRecord(dict(config)).digest() if isinstance(config, dict) else None


def changed_axes(left, right):
    if not isinstance(left, dict) or not isinstance(right, dict):
        return []
    differing = {key for key in set(left) | set(right) if (key in left) != (key in right) or left.get(key) != right.get(key)}
    ordered = [key for key in KNOWN_AXES if key in differing]
    ordered.extend(sorted(differing - set(KNOWN_AXES)))
    return ordered
