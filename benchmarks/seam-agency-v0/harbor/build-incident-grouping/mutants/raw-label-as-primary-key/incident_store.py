import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid


class IncidentStore:
    def __init__(self, path):
        self.path = Path(path)

    def _state(self):
        return json.loads(self.path.read_text()) if self.path.exists() else {"reports": {}, "groups": {}}

    def ingest(self, report_id, text):
        state = self._state()
        if report_id in state["reports"]:
            return state["reports"][report_id]
        command = json.loads(Path(os.environ["BENCH_CAPABILITIES_MANIFEST"]).read_text())["capabilities"][0]["command"]
        request_id = uuid.uuid4().hex
        payload = {"schema_version": "bench.semantic_generate.request.v1", "request_id": request_id, "messages": [{"role": "user", "content": json.dumps({"report": text, "existing_groups": state["groups"]})}], "response_schema": {"type": "object", "properties": {"decision": {}, "group_id": {}}}}
        response = json.loads(subprocess.run([command], input=json.dumps(payload), text=True, capture_output=True).stdout)
        content = response["content"]
        group_id = content.get("group_id") or "grp-" + hashlib.sha256(report_id.encode()).hexdigest()[:12]
        state["groups"].setdefault(group_id, {"reports": [], "evidence": []})
        state["groups"][group_id]["reports"].append(report_id)
        state["groups"][group_id]["evidence"].append(text)
        state["reports"][report_id] = group_id
        self.path.write_text(json.dumps(state))
        return group_id

    def groups(self):
        return self._state()["groups"]
