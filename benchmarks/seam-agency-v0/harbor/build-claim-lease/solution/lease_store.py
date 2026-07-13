"""Reference solution for the clean-room exact lease task."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile


class LeaseStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    @staticmethod
    def _valid(owner: str, now: int, ttl: int) -> bool:
        return (
            isinstance(owner, str)
            and bool(owner)
            and type(now) is int
            and now >= 0
            and type(ttl) is int
            and ttl > 0
        )

    def _read(self) -> dict | None:
        try:
            value = json.loads(self.path.read_text())
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(value, dict) or set(value) != {"owner", "expires_at"}:
            return None
        if not isinstance(value["owner"], str) or type(value["expires_at"]) is not int:
            return None
        return value

    def _write(self, owner: str, expires_at: int) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=self.path.parent, delete=False
            ) as handle:
                temp_name = handle.name
                json.dump({"owner": owner, "expires_at": expires_at}, handle, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
            temp_name = None
        finally:
            if temp_name is not None:
                Path(temp_name).unlink(missing_ok=True)

    def acquire(self, owner: str, now: int, ttl: int) -> bool:
        if not self._valid(owner, now, ttl):
            return False
        current = self._read()
        if current is not None and now < current["expires_at"]:
            return False
        self._write(owner, now + ttl)
        return True

    def renew(self, owner: str, now: int, ttl: int) -> bool:
        if not self._valid(owner, now, ttl):
            return False
        current = self._read()
        if current is None or current["owner"] != owner or now >= current["expires_at"]:
            return False
        self._write(owner, now + ttl)
        return True

    def holder(self, now: int) -> str | None:
        if type(now) is not int or now < 0:
            return None
        current = self._read()
        if current is None or now >= current["expires_at"]:
            return None
        return current["owner"]
