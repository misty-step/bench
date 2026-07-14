"""Reference solution: functional semantic adapter plus atomic file mechanism."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Sequence
import uuid


_CREDENTIALS = (
    re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|password)\s*[:=]\s*\S+"),
    re.compile(r"\bAKIA[0-9A-Z]{12,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
)


def _has_credential_shape(text: str) -> bool:
    return any(pattern.search(text) for pattern in _CREDENTIALS)


def _capability_command() -> str | None:
    try:
        manifest = json.loads(Path(os.environ["BENCH_CAPABILITIES_MANIFEST"]).read_text())
        capability = next(
            item for item in manifest["capabilities"] if item["id"] == "semantic.generate.v1"
        )
        if (
            manifest["schema_version"] != "bench.runtime_capabilities.v1"
            or capability["transport"] != "json_stdio_once"
            or not isinstance(capability["command"], str)
        ):
            return None
        return capability["command"] if shutil.which(capability["command"]) else None
    except (KeyError, OSError, TypeError, ValueError, StopIteration):
        return None


def _response_schema(declared: tuple[str, ...]) -> dict:
    string_fields = {field: {"type": "string"} for field in declared}
    return {
        "type": "object",
        "required": ["decision", "fields"],
        "properties": {
            "decision": {"enum": ["publish", "withhold"]},
            "fields": {
                "type": "object",
                "properties": string_fields,
                "additionalProperties": False,
            },
        },
        "additionalProperties": False,
    }


def _generate(draft: str, declared: tuple[str, ...]) -> object | None:
    command = _capability_command()
    if command is None:
        return None
    request_id = uuid.uuid4().hex
    request = {
        "schema_version": "bench.semantic_generate.request.v1",
        "request_id": request_id,
        "messages": [
            {
                "role": "system",
                "content": "Decide whether the draft is appropriate for public release and return only the requested fields.",
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"draft": draft, "declared_fields": list(declared)}, sort_keys=True
                ),
            },
        ],
        "response_schema": _response_schema(declared),
    }
    try:
        completed = subprocess.run(
            [command],
            input=json.dumps(request) + "\n",
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        if completed.returncode != 0:
            return None
        envelope = json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, TypeError):
        return None
    if (
        not isinstance(envelope, dict)
        or envelope.get("schema_version") != "bench.semantic_generate.result.v1"
        or envelope.get("request_id") != request_id
        or envelope.get("status") != "ok"
    ):
        return None
    return envelope.get("content")


def _validated_fields(content: object, declared: tuple[str, ...]) -> dict[str, str] | None:
    if not isinstance(content, dict) or set(content) != {"decision", "fields"}:
        return None
    if content["decision"] == "withhold" and content["fields"] == {}:
        return {}
    if content["decision"] != "publish" or not isinstance(content["fields"], dict):
        return None
    fields = content["fields"]
    if set(fields) != set(declared) or any(not isinstance(value, str) for value in fields.values()):
        return None
    if any(_has_credential_shape(value) for value in fields.values()):
        return None
    return {field: fields[field] for field in declared}


def publish_packet(
    draft: str,
    declared_fields: Sequence[str],
    destination: str | Path,
) -> bool:
    """Publish an accepted packet; return False for a safe refusal."""
    if not isinstance(draft, str) or _has_credential_shape(draft):
        return False
    declared = tuple(declared_fields)
    if (
        not declared
        or len(set(declared)) != len(declared)
        or any(not isinstance(field, str) or not field for field in declared)
    ):
        return False
    fields = _validated_fields(_generate(draft, declared), declared)
    if not fields:
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
    except OSError:
        return False
    finally:
        if temp_name is not None:
            Path(temp_name).unlink(missing_ok=True)
