"""Persistent incident grouping API."""


class IncidentStore:
    def __init__(self, path):
        self.path = path

    def ingest(self, report_id, text):
        raise NotImplementedError

    def groups(self):
        raise NotImplementedError
