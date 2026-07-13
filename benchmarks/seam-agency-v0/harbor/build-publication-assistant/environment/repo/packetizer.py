"""Safe publication exercise. Implement publish_packet without new packages."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, Sequence


class ReviewBoundary(Protocol):
    def review(self, draft: str, declared_fields: Sequence[str]) -> str:
        """Return a JSON decision and proposed fields for the draft."""


def publish_packet(
    draft: str,
    declared_fields: Sequence[str],
    reviewer: ReviewBoundary,
    destination: str | Path,
) -> bool:
    """Publish an accepted packet; return False for a safe refusal."""
    raise NotImplementedError
