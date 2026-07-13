"""Safe publication exercise. Implement publish_packet without new packages."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence


def publish_packet(
    draft: str,
    declared_fields: Sequence[str],
    destination: str | Path,
) -> bool:
    """Publish an accepted packet; return False for a safe refusal."""
    raise NotImplementedError
