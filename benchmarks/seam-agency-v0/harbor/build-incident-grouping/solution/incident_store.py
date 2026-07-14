from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import uuid


REQUEST = "bench.semantic_generate.request.v1"
RESULT = "bench.semantic_generate.result.v1"


def _semantic(report_id: str, text: str, groups: dict) -> dict | None:
    manifest_path = os.environ.get("BENCH_CAPABILITIES_MANIFEST")
    if not manifest_path:
        return None
    try:
        manifest = json.loads(Path(manifest_path).read_text())
        capability = next(item for item in manifest["capabilities"] if item["id"] == "semantic.generate.v1")
        request_id = uuid.uuid4().hex
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["decision", "group_id"],
            "properties": {
                "decision": {"enum": ["new", "join"]},
                "group_id": {"type": ["string", "null"]},
            },
        }
        payload = {
            "schema_version": REQUEST,
            "request_id": request_id,
            "messages": [
                {"role": "system", "content": "Decide whether this report joins an existing incident group or starts a new one."},
                {"role": "user", "content": json.dumps({"report_id": report_id, "report": text, "existing_groups": groups}, sort_keys=True)},
            ],
            "response_schema": schema,
        }
        completed = subprocess.run(
            [capability["command"]], input=json.dumps(payload), text=True,
            capture_output=True, timeout=10, check=False,
        )
        response = json.loads(completed.stdout)
    except (OSError, ValueError, KeyError, StopIteration, subprocess.TimeoutExpired):
        return None
    if response.get("schema_version") != RESULT or response.get("request_id") != request_id or response.get("status") != "ok":
        return None
    content = response.get("content")
    if not isinstance(content, dict) or set(content) != {"decision", "group_id"}:
        return None
    if content["decision"] not in {"new", "join"}:
        return None
    if content["decision"] == "join" and content["group_id"] not in groups:
        return None
    if content["decision"] == "new" and content["group_id"] is not None:
        return None
    return content


class IncidentStore:
    def __init__(self, path):
        self.path = Path(path)

    def _read(self) -> dict:
        if not self.path.exists():
            return {"reports": {}, "groups": {}}
        try:
            state = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return {"reports": {}, "groups": {}}
        if not isinstance(state, dict) or not isinstance(state.get("reports"), dict) or not isinstance(state.get("groups"), dict):
            return {"reports": {}, "groups": {}}
        return state

    def _write(self, state: dict) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.NamedTemporaryFile("w", dir=self.path.parent, delete=False) as handle:
                json.dump(state, handle, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                temp = handle.name
            os.replace(temp, self.path)
            return True
        except OSError:
            try:
                os.unlink(temp)
            except (OSError, UnboundLocalError):
                pass
            return False

    def ingest(self, report_id, text):
        if not isinstance(report_id, str) or not report_id or not isinstance(text, str) or not text.strip():
            return None
        state = self._read()
        if report_id in state["reports"]:
            return state["reports"][report_id]
        summaries = {
            group_id: {"evidence": group.get("evidence", []), "report_ids": group.get("reports", [])}
            for group_id, group in state["groups"].items()
        }
        decision = _semantic(report_id, text, summaries)
        if decision is None:
            return None
        if decision["decision"] == "join":
            group_id = decision["group_id"]
        else:
            group_id = "grp-" + hashlib.sha256(report_id.encode()).hexdigest()[:12]
            if group_id in state["groups"]:
                return None
            state["groups"][group_id] = {"reports": [], "evidence": []}
        state["groups"][group_id]["reports"].append(report_id)
        state["groups"][group_id]["evidence"].append(text)
        state["reports"][report_id] = group_id
        return group_id if self._write(state) else None

    def groups(self):
        return self._read()["groups"]
