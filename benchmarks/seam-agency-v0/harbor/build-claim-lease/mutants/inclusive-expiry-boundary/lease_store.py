from __future__ import annotations
import json
from pathlib import Path


class LeaseStore:
    def __init__(self, path):
        self.path = Path(path)

    def _read(self):
        return json.loads(self.path.read_text()) if self.path.exists() else None

    def _write(self, owner, expires_at):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"owner": owner, "expires_at": expires_at}) + "\n")

    def acquire(self, owner, now, ttl):
        current = self._read()
        if current and now <= current["expires_at"]:
            return False
        self._write(owner, now + ttl)
        return True

    def renew(self, owner, now, ttl):
        current = self._read()
        if not current or current["owner"] != owner or now > current["expires_at"]:
            return False
        self._write(owner, now + ttl)
        return True

    def holder(self, now):
        current = self._read()
        return current["owner"] if current and now <= current["expires_at"] else None
