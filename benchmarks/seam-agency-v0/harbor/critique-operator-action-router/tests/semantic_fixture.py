"""Verifier-owned deterministic semantic capability and candidate isolation."""

from __future__ import annotations

import json
import os
from pathlib import Path
import pwd
import shutil
import socket
import subprocess
import sys
import tempfile
import threading


REQUEST_SCHEMA = "bench.semantic_generate.request.v1"
RESULT_SCHEMA = "bench.semantic_generate.result.v1"


class SemanticFixture:
    def __init__(self, scenario: str, response: dict | bytes, ledger: list[dict]):
        self.scenario = scenario
        self.response_template = response
        self.ledger = ledger
        self.records: list[dict] = []
        self._stop = threading.Event()
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._roots: list[Path] = []

    def __enter__(self):
        require_isolation = os.environ.get("BENCH_REQUIRE_ISOLATION") == "1"
        if require_isolation and os.geteuid() != 0:
            raise AssertionError("Harbor verifier isolation requires root")
        private_root = Path(tempfile.mkdtemp(prefix="bench-semantic-receipt-"))
        private_root.chmod(0o700 if os.geteuid() == 0 else 0o000)
        public_root = Path(tempfile.mkdtemp(prefix="bench-semantic-socket-"))
        public_root.chmod(0o755)
        self._roots.extend((private_root, public_root))
        self.receipt_canary = private_root / "candidate-cannot-author.jsonl"
        self.socket_path = public_root / "broker.sock"
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(str(self.socket_path))
        self.socket_path.chmod(0o666)
        self._server.listen(8)
        self._server.settimeout(0.1)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        return self

    def _serve(self) -> None:
        assert self._server is not None
        while not self._stop.is_set():
            try:
                connection, _ = self._server.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            with connection:
                payload = bytearray()
                while True:
                    chunk = connection.recv(65536)
                    if not chunk:
                        break
                    payload.extend(chunk)
                try:
                    request = json.loads(payload)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    request = {"raw": payload.decode(errors="replace")}
                if isinstance(self.response_template, bytes):
                    response_bytes = self.response_template
                    response_for_receipt = {"raw": response_bytes.decode(errors="replace")}
                else:
                    response_for_receipt = dict(self.response_template)
                    response_for_receipt["request_id"] = request.get("request_id")
                    response_bytes = (json.dumps(response_for_receipt) + "\n").encode()
                record = {
                    "scenario": self.scenario,
                    "sequence": len(self.records) + 1,
                    "request": request,
                    "response": response_for_receipt,
                }
                self.records.append(record)
                connection.sendall(response_bytes)

    def environment(self, *, capability_present: bool = True) -> dict[str, str]:
        environment = os.environ.copy()
        environment["BENCH_RECEIPT_CANARY"] = str(self.receipt_canary)
        if capability_present:
            environment["CRUCIBLE_SEMANTIC_SOCKET"] = str(self.socket_path)
            environment["PATH"] = str(Path(__file__).parent) + os.pathsep + environment["PATH"]
            if "BENCH_CAPABILITIES_MANIFEST" not in environment:
                environment["BENCH_CAPABILITIES_MANIFEST"] = str(
                    Path(__file__).parents[1] / "environment" / "capabilities.json"
                )
        else:
            environment.pop("CRUCIBLE_SEMANTIC_SOCKET", None)
            environment.pop("BENCH_CAPABILITIES_MANIFEST", None)
            environment["PATH"] = "/usr/bin:/bin"
            for key in tuple(environment):
                if key.endswith("_API_KEY") or key.endswith("_TOKEN") or key in {
                    "ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"
                }:
                    environment.pop(key, None)
        return environment

    @staticmethod
    def _drop_privileges() -> None:
        nobody = pwd.getpwnam("nobody")
        os.setgid(nobody.pw_gid)
        os.setuid(nobody.pw_uid)

    def spawn_driver(
        self,
        driver: Path,
        repo: Path,
        payload: dict,
        *,
        capability_present: bool = True,
    ) -> subprocess.Popen:
        preexec = self._drop_privileges if os.geteuid() == 0 else None
        return subprocess.Popen(
            [sys.executable, str(driver), str(repo)],
            cwd=repo,
            env=self.environment(capability_present=capability_present),
            text=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=preexec,
        )

    @staticmethod
    def finish_driver(process: subprocess.Popen, payload: dict | None) -> dict:
        if payload is None:
            assert process.stdout is not None and process.stderr is not None
            stdout = process.stdout.read()
            stderr = process.stderr.read()
            process.wait(timeout=20)
        else:
            stdout, stderr = process.communicate(json.dumps(payload), timeout=20)
        if process.returncode != 0:
            raise AssertionError(f"candidate driver failed: {stdout} {stderr}")
        try:
            report = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise AssertionError(f"candidate driver returned invalid JSON: {stdout} {stderr}") from exc
        if report.get("receipt_write_blocked") is not True:
            raise AssertionError("candidate process could author verifier receipt")
        return report

    def run_driver(
        self,
        driver: Path,
        repo: Path,
        payload: dict,
        *,
        capability_present: bool = True,
    ) -> dict:
        process = self.spawn_driver(
            driver, repo, payload, capability_present=capability_present
        )
        return self.finish_driver(process, payload)

    def __exit__(self, exc_type, exc, traceback):
        self._stop.set()
        if self._server is not None:
            self._server.close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self.ledger.extend(self.records)
        for root in self._roots:
            root.chmod(0o700)
            shutil.rmtree(root, ignore_errors=True)


def result(request_id: str, status: str, **fields) -> dict:
    return {
        "schema_version": RESULT_SCHEMA,
        "request_id": request_id,
        "status": status,
        **fields,
    }


def write_receipt(ledger: list[dict], summary: dict) -> None:
    lines = [json.dumps({"summary": summary}, sort_keys=True)]
    lines.extend(json.dumps(record, sort_keys=True) for record in ledger)
    logs = Path("/logs/verifier")
    if logs.is_dir():
        path = logs / "semantic-invocations.jsonl"
        path.unlink(missing_ok=True)
        path.write_text("\n".join(lines) + "\n")
        path.chmod(0o600)
    for line in lines:
        print(f"semantic-invocation-receipt: {line}")
