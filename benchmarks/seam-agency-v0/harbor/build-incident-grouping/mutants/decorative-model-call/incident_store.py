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
        manifest = json.loads(Path(os.environ["BENCH_CAPABILITIES_MANIFEST"]).read_text())
        command = manifest["capabilities"][0]["command"]
        payload = {"schema_version": "bench.semantic_generate.request.v1", "request_id": uuid.uuid4().hex, "messages": [{"role": "user", "content": json.dumps({"report": text, "existing_groups": state["groups"]})}], "response_schema": {"type": "object", "properties": {"decision": {}, "group_id": {}}}}
        subprocess.run([command], input=json.dumps(payload), text=True, capture_output=True)
        group_id = "grp-" + hashlib.sha256(report_id.encode()).hexdigest()[:12]
        state["groups"][group_id] = {"reports": [report_id], "evidence": [text]}
        state["reports"][report_id] = group_id
        self.path.write_text(json.dumps(state))
        return group_id

    def groups(self):
        return self._state()["groups"]
