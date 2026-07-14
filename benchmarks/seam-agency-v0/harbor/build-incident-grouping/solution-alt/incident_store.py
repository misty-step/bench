from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid


class SemanticGrouping:
    def decide(self, report_id: str, report: str, groups: dict) -> tuple[str, str | None] | None:
        location = os.environ.get("BENCH_CAPABILITIES_MANIFEST")
        if not location:
            return None
        try:
            declaration = json.loads(Path(location).read_text())
            command = next(value["command"] for value in declaration["capabilities"] if value["id"] == "semantic.generate.v1")
            request_id = uuid.uuid4().hex
            payload = {
                "schema_version": "bench.semantic_generate.request.v1",
                "request_id": request_id,
                "messages": [
                    {"role": "user", "content": json.dumps({"report_id": report_id, "full_report": report, "available_groups": groups}, sort_keys=True)},
                ],
                "response_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["decision", "group_id"],
                    "properties": {"decision": {"enum": ["new", "join"]}, "group_id": {"type": ["string", "null"]}},
                },
            }
            process = subprocess.Popen([command], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stdout, _ = process.communicate(json.dumps(payload), timeout=10)
            envelope = json.loads(stdout)
        except (OSError, ValueError, KeyError, StopIteration, subprocess.TimeoutExpired):
            return None
        if envelope.get("schema_version") != "bench.semantic_generate.result.v1" or envelope.get("request_id") != request_id or envelope.get("status") != "ok":
            return None
        answer = envelope.get("content")
        if not isinstance(answer, dict) or set(answer) != {"decision", "group_id"}:
            return None
        choice = answer.get("decision")
        group_id = answer.get("group_id")
        if choice == "new" and group_id is None:
            return choice, None
        if choice == "join" and isinstance(group_id, str) and group_id in groups:
            return choice, group_id
        return None


class IncidentStore:
    def __init__(self, path):
        self.path = Path(path)
        self.semantic = SemanticGrouping()

    def _snapshot(self):
        if not self.path.exists():
            return {"reports": {}, "groups": {}}
        try:
            value = json.loads(self.path.read_text())
            if isinstance(value.get("reports"), dict) and isinstance(value.get("groups"), dict):
                return value
        except (OSError, ValueError, AttributeError):
            pass
        return {"reports": {}, "groups": {}}

    def _commit(self, value):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        staging = self.path.parent / f".{self.path.name}.{uuid.uuid4().hex}.stage"
        try:
            descriptor = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as handle:
                handle.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
            os.replace(staging, self.path)
            return True
        except OSError:
            staging.unlink(missing_ok=True)
            return False

    def ingest(self, report_id, text):
        if type(report_id) is not str or not report_id or type(text) is not str or not text.strip():
            return None
        state = self._snapshot()
        previous = state["reports"].get(report_id)
        if previous is not None:
            return previous
        public_groups = {key: {"report_ids": value["reports"], "evidence": value["evidence"]} for key, value in state["groups"].items()}
        outcome = self.semantic.decide(report_id, text, public_groups)
        if outcome is None:
            return None
        decision, selected = outcome
        if decision == "new":
            selected = "grp-" + hashlib.sha256(text.encode()).hexdigest()[:12]
            if selected in state["groups"]:
                return None
            state["groups"][selected] = {"reports": [], "evidence": []}
        state["groups"][selected]["reports"] += [report_id]
        state["groups"][selected]["evidence"] += [text]
        ordered = sorted(zip(state["groups"][selected]["reports"], state["groups"][selected]["evidence"]))
        state["groups"][selected]["reports"] = [item[0] for item in ordered]
        state["groups"][selected]["evidence"] = [item[1] for item in ordered]
        state["reports"][report_id] = selected
        return selected if self._commit(state) else None

    def groups(self):
        return self._snapshot()["groups"]
