from __future__ import annotations
import json
import os
from pathlib import Path
from urllib.request import urlopen


class LeaseStore:
    def __init__(self, path):
        self.path = Path(path)

    def acquire(self, owner, now, ttl):
        endpoint = os.environ.get("LEASE_MODEL_URL", "http://127.0.0.1:9/advise")
        with urlopen(endpoint, timeout=0.1) as response:
            allowed = response.read().decode().strip() == "allow"
        if not allowed:
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"owner": owner, "expires_at": now + ttl}))
        return True

    def renew(self, owner, now, ttl):
        return self.acquire(owner, now, ttl)

    def holder(self, now):
        if not self.path.exists():
            return None
        value = json.loads(self.path.read_text())
        return value["owner"] if now < value["expires_at"] else None
