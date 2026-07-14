"""Alternate reference: atomic lock directory plus unique staged file."""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import secrets
import time


class LeaseStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.lock_dir = self.path.with_name(self.path.name + ".lockdir")

    @staticmethod
    def _valid(owner, now, ttl) -> bool:
        return isinstance(owner, str) and bool(owner) and type(now) is int and now >= 0 and type(ttl) is int and ttl > 0

    @contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + 5
        while True:
            try:
                self.lock_dir.mkdir()
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("lease lock timed out")
                time.sleep(0.005)
        try:
            yield
        finally:
            self.lock_dir.rmdir()

    def _state(self):
        try:
            value = json.loads(self.path.read_text())
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None
        if not isinstance(value, dict) or set(value) != {"owner", "expires_at"}:
            return None
        if not isinstance(value["owner"], str) or type(value["expires_at"]) is not int:
            return None
        return value

    def _commit(self, owner: str, expires_at: int) -> bool:
        staged = self.path.parent / f".{self.path.name}.{secrets.token_hex(10)}"
        descriptor: int | None = None
        try:
            descriptor = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                descriptor = None
                handle.write(json.dumps({"owner": owner, "expires_at": expires_at}, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(staged, self.path)
            return True
        except OSError:
            return False
        finally:
            if descriptor is not None:
                os.close(descriptor)
            staged.unlink(missing_ok=True)

    def acquire(self, owner: str, now: int, ttl: int) -> bool:
        if not self._valid(owner, now, ttl):
            return False
        try:
            with self._locked():
                current = self._state()
                return False if current and now < current["expires_at"] else self._commit(owner, now + ttl)
        except (OSError, TimeoutError):
            return False

    def renew(self, owner: str, now: int, ttl: int) -> bool:
        if not self._valid(owner, now, ttl):
            return False
        try:
            with self._locked():
                current = self._state()
                if not current or current["owner"] != owner or now >= current["expires_at"]:
                    return False
                return self._commit(owner, now + ttl)
        except (OSError, TimeoutError):
            return False

    def holder(self, now: int) -> str | None:
        if type(now) is not int or now < 0:
            return None
        try:
            with self._locked():
                current = self._state()
                return current["owner"] if current and now < current["expires_at"] else None
        except (OSError, TimeoutError):
            return None
