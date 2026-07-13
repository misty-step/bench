"""Reference solution for the clean-room publication assistant task."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
from typing import Protocol, Sequence


class ReviewBoundary(Protocol):
    def review(self, draft: str, declared_fields: Sequence[str]) -> str:
        """Return a JSON decision and proposed fields for the draft."""


_CREDENTIALS = (
    re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|password)\s*[:=]\s*\S+"),
    re.compile(r"\bAKIA[0-9A-Z]{12,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
)


def _has_credential_shape(text: str) -> bool:
    return any(pattern.search(text) for pattern in _CREDENTIALS)


def _review(raw: str, declared: tuple[str, ...]) -> dict[str, str] | None:
    try:
        result = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(result, dict) or set(result) != {"decision", "fields"}:
        return None
    if result["decision"] == "withhold":
        return {}
    if result["decision"] != "publish" or not isinstance(result["fields"], dict):
        return None
    fields = result["fields"]
    if set(fields) != set(declared):
        return None
    if any(not isinstance(value, str) for value in fields.values()):
        return None
    if any(_has_credential_shape(value) for value in fields.values()):
        return None
    return {field: fields[field] for field in declared}


def publish_packet(
    draft: str,
    declared_fields: Sequence[str],
    reviewer: ReviewBoundary,
    destination: str | Path,
) -> bool:
    """Publish an accepted packet; return False for a safe refusal."""
    if not isinstance(draft, str) or _has_credential_shape(draft):
        return False
    declared = tuple(declared_fields)
    if not declared or len(set(declared)) != len(declared):
        return False
    if any(not isinstance(field, str) or not field for field in declared):
        return False

    fields = _review(reviewer.review(draft, declared), declared)
    if fields is None or fields == {}:
        return False

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    packet = {"schema_version": "bench.publication_packet.v0", "fields": fields}
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=destination.parent, delete=False
        ) as handle:
            temp_name = handle.name
            json.dump(packet, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, destination)
        temp_name = None
        return True
    finally:
        if temp_name is not None:
            Path(temp_name).unlink(missing_ok=True)
