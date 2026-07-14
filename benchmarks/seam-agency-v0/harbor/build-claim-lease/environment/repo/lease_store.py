"""Exact claim lease exercise. Implement LeaseStore without new packages."""

from __future__ import annotations

from pathlib import Path


class LeaseStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def acquire(self, owner: str, now: int, ttl: int) -> bool:
        raise NotImplementedError

    def renew(self, owner: str, now: int, ttl: int) -> bool:
        raise NotImplementedError

    def holder(self, now: int) -> str | None:
        raise NotImplementedError
