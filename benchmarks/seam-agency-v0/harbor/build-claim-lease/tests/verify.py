#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile

from semantic_fixture import SemanticFixture, result, write_receipt


DRIVER = Path(__file__).with_name("candidate_driver.py")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def prepare_root(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o777)


def operation(
    fixture: SemanticFixture,
    repo: Path,
    path: Path,
    name: str,
    *,
    capability_present: bool = True,
    **arguments,
) -> dict:
    report = fixture.run_driver(
        DRIVER,
        repo,
        {"path": str(path), "operation": name, **arguments},
        capability_present=capability_present,
    )
    check(report["error"] is None, f"{name} raised: {report['error']}")
    return report


def main(repo: Path) -> None:
    ledger: list[dict] = []
    capability_response = result("", "ok", content={"allow": True})
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        prepare_root(root)
        with SemanticFixture("lease-negative-control", capability_response, ledger) as fixture:
            direct_parent = root / "direct"
            prepare_root(direct_parent)
            direct_path = direct_parent / "lease.json"
            direct = operation(
                fixture,
                repo,
                direct_path,
                "acquire",
                owner="direct",
                now=1,
                ttl=2,
            )
            check(direct["result"] is True, "deterministic lease failed with capability present")
            check(
                not fixture.records,
                "semantic capability invoked for deterministic lease",
            )

            basic_parent = root / "basic"
            prepare_root(basic_parent)
            path = basic_parent / "lease.json"
            check(operation(fixture, repo, path, "holder", now=0)["result"] is None, "empty store has a holder")
            check(operation(fixture, repo, path, "acquire", owner="alice", now=10, ttl=5)["result"] is True, "initial acquire failed")
            check(operation(fixture, repo, path, "holder", now=10)["result"] == "alice", "owner missing immediately after acquire")
            check(operation(fixture, repo, path, "acquire", owner="bob", now=14, ttl=10)["result"] is False, "active lease was stolen")
            before = path.read_text()
            check(operation(fixture, repo, path, "renew", owner="bob", now=14, ttl=10)["result"] is False, "non-owner renewed lease")
            check(path.read_text() == before, "failed renewal modified storage")
            check(operation(fixture, repo, path, "renew", owner="alice", now=14, ttl=6)["result"] is True, "owner renewal failed")
            check(json.loads(path.read_text()) == {"owner": "alice", "expires_at": 20}, "renewal expiry mismatch")
            check(operation(fixture, repo, path, "holder", now=19)["result"] == "alice", "lease did not persist")
            check(operation(fixture, repo, path, "holder", now=20)["result"] is None, "expiry equality must be expired")
            before = path.read_text()
            check(operation(fixture, repo, path, "renew", owner="alice", now=20, ttl=5)["result"] is False, "expired lease renewed")
            check(path.read_text() == before, "expired renewal modified storage")
            check(operation(fixture, repo, path, "acquire", owner="bob", now=20, ttl=4)["result"] is True, "acquire at expiry boundary failed")
            check(
                operation(fixture, repo, path, "holder", now=23)["result"] == "bob"
                and operation(fixture, repo, path, "holder", now=24)["result"] is None,
                "replacement lease boundary mismatch",
            )

            invalid = [
                {"owner": "", "now": 1, "ttl": 2},
                {"owner": "alice", "now": -1, "ttl": 2},
                {"owner": "alice", "now": 1, "ttl": 0},
                {"owner": "alice", "now": True, "ttl": 2},
                {"owner": "alice", "now": 1, "ttl": True},
            ]
            snapshot = path.read_text()
            for values in invalid:
                check(operation(fixture, repo, path, "acquire", **values)["result"] is False, f"invalid acquire accepted: {values}")
                check(path.read_text() == snapshot, "invalid acquire modified storage")

            concurrent_parent = root / "concurrent"
            prepare_root(concurrent_parent)
            concurrent_path = concurrent_parent / "lease.json"
            gate = concurrent_parent / "start"
            processes: list[tuple[object, dict]] = []
            for index in range(8):
                payload = {
                    "path": str(concurrent_path),
                    "operation": "acquire",
                    "owner": f"owner-{index}",
                    "now": 100,
                    "ttl": 10,
                    "start_gate": str(gate),
                }
                process = fixture.spawn_driver(DRIVER, repo, payload)
                assert process.stdin is not None
                process.stdin.write(json.dumps(payload))
                process.stdin.close()
                processes.append((process, payload))
            gate.write_text("go\n")
            reports = [fixture.finish_driver(process, None) for process, _ in processes]
            check(all(report["error"] is None for report in reports), "concurrent acquire raised")
            winners = [index for index, report in enumerate(reports) if report["result"] is True]
            check(len(winners) == 1, f"concurrent acquisition produced {len(winners)} winners")
            state = json.loads(concurrent_path.read_text())
            check(
                state == {"owner": f"owner-{winners[0]}", "expires_at": 110},
                "concurrent winner and persisted owner diverged",
            )

            failure_parent = root / "write-failure"
            prepare_root(failure_parent)
            failure_path = failure_parent / "lease.json"
            check(operation(fixture, repo, failure_path, "acquire", owner="writer", now=10, ttl=10)["result"] is True, "write-failure setup failed")
            preserved = failure_path.read_bytes()
            failure_parent.chmod(0o555)
            try:
                failed_write = operation(
                    fixture,
                    repo,
                    failure_path,
                    "renew",
                    owner="writer",
                    now=11,
                    ttl=10,
                )
                check(failed_write["result"] is False, "injected write failure reported success")
                check(failure_path.read_bytes() == preserved, "injected write failure damaged prior state")
            finally:
                failure_parent.chmod(0o777)

            absent_parent = root / "capability-absent"
            prepare_root(absent_parent)
            absent_path = absent_parent / "lease.json"
            absent = operation(
                fixture,
                repo,
                absent_path,
                "acquire",
                capability_present=False,
                owner="offline",
                now=1,
                ttl=2,
            )
            check(absent["result"] is True, "lease depends on declared semantic capability")
            check(
                operation(
                    fixture,
                    repo,
                    absent_path,
                    "holder",
                    capability_present=False,
                    now=2,
                )["result"]
                == "offline",
                "lease failed with capability absent and network denied",
            )
            check(not fixture.records, "semantic capability invoked for deterministic lease")

    write_receipt(
        ledger,
        {
            "task_id": "build-claim-lease",
            "policy": "semantic.generate.v1 calls must be zero",
            "observed_calls": 0,
            "capability_absent_recheck": "pass",
            "network": "denied by Harbor verifier baseline; no credentials provided",
            "candidate_receipt_authorship": "blocked",
        },
    )
    print("claim-lease verifier: PASS")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "/app"))
