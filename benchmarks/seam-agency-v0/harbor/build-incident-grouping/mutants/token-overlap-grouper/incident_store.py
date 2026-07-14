import hashlib
import json
from pathlib import Path


class IncidentStore:
    def __init__(self, path):
        self.path = Path(path)

    def _state(self):
        return json.loads(self.path.read_text()) if self.path.exists() else {"reports": {}, "groups": {}}

    def ingest(self, report_id, text):
        state = self._state()
        if report_id in state["reports"]:
            return state["reports"][report_id]
        words = set(text.lower().split())
        selected = None
        for group_id, group in state["groups"].items():
            if any(len(words & set(value.lower().split())) >= 3 for value in group["evidence"]):
                selected = group_id
        if selected is None:
            selected = "grp-" + hashlib.sha256(report_id.encode()).hexdigest()[:12]
            state["groups"][selected] = {"reports": [], "evidence": []}
        state["groups"][selected]["reports"].append(report_id)
        state["groups"][selected]["evidence"].append(text)
        state["reports"][report_id] = selected
        self.path.write_text(json.dumps(state))
        return selected

    def groups(self):
        return self._state()["groups"]
