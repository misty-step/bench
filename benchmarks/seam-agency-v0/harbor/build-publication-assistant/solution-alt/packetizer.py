"""Alternate reference: object adapter plus directory-relative atomic writer."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets
import subprocess
from typing import Sequence


_SECRET = re.compile(
    r"(?i)(?:\b(?:api[_-]?key|access[_-]?token|password)\s*[:=]\s*\S+|\bAKIA[0-9A-Z]{12,}\b|\bsk-[A-Za-z0-9_-]{12,}\b)"
)


class SemanticGenerator:
    def __init__(self) -> None:
        document = json.loads(Path(os.environ["BENCH_CAPABILITIES_MANIFEST"]).read_text())
        entries = {
            entry.get("id"): entry for entry in document.get("capabilities", []) if isinstance(entry, dict)
        }
        selected = entries["semantic.generate.v1"]
        if document.get("schema_version") != "bench.runtime_capabilities.v1":
            raise ValueError("unsupported manifest")
        if selected.get("transport") != "json_stdio_once":
            raise ValueError("unsupported transport")
        self.command = selected["command"]

    def decide(self, draft: str, fields: tuple[str, ...]) -> object:
        request_id = secrets.token_hex(12)
        field_shape = {field: {"type": "string"} for field in fields}
        request = {
            "schema_version": "bench.semantic_generate.request.v1",
            "request_id": request_id,
            "messages": [
                {"role": "user", "content": draft},
                {"role": "user", "content": json.dumps({"declared_fields": fields})},
            ],
            "response_schema": {
                "type": "object",
                "required": ["decision", "fields"],
                "properties": {
                    "decision": {"enum": ["publish", "withhold"]},
                    "fields": {
                        "type": "object",
                        "properties": field_shape,
                        "additionalProperties": False,
                    },
                },
                "additionalProperties": False,
            },
        }
        process = subprocess.Popen(
            [self.command], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        stdout, _ = process.communicate(json.dumps(request) + "\n", timeout=10)
        if process.returncode != 0:
            raise RuntimeError("semantic capability failed")
        envelope = json.loads(stdout)
        if (
            envelope.get("schema_version") != "bench.semantic_generate.result.v1"
            or envelope.get("request_id") != request_id
            or envelope.get("status") != "ok"
        ):
            raise ValueError("semantic capability refused")
        return envelope.get("content")


def _safe(text: str) -> bool:
    return isinstance(text, str) and _SECRET.search(text) is None


def _packet(content: object, fields: tuple[str, ...]) -> dict | None:
    if not isinstance(content, dict) or set(content) != {"decision", "fields"}:
        return None
    values = content["fields"]
    if content["decision"] == "withhold" and values == {}:
        return None
    if content["decision"] != "publish" or not isinstance(values, dict):
        return None
    if set(values) != set(fields) or any(not _safe(value) for value in values.values()):
        return None
    return {
        "schema_version": "bench.publication_packet.v0",
        "fields": {field: values[field] for field in fields},
    }


def _commit(packet: dict, destination: Path) -> bool:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.{secrets.token_hex(8)}"
    descriptor: int | None = None
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = None
            handle.write(json.dumps(packet, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        return True
    except OSError:
        return False
    finally:
        if descriptor is not None:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def publish_packet(draft: str, declared_fields: Sequence[str], destination: str | Path) -> bool:
    fields = tuple(declared_fields)
    if not _safe(draft) or not fields or len(fields) != len(set(fields)):
        return False
    if any(not isinstance(field, str) or not field for field in fields):
        return False
    try:
        packet = _packet(SemanticGenerator().decide(draft, fields), fields)
    except (KeyError, OSError, TypeError, ValueError, subprocess.SubprocessError, json.JSONDecodeError):
        return False
    return packet is not None and _commit(packet, Path(destination))
