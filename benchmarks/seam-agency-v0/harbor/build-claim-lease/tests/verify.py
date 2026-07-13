#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile


def load(repo: Path):
    spec = importlib.util.spec_from_file_location("candidate_lease_store", repo / "lease_store.py")
    if spec is None or spec.loader is None:
        raise AssertionError("lease_store.py cannot be imported")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main(repo: Path) -> None:
    candidate = load(repo)
    os.environ.pop("LEASE_MODEL_URL", None)
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "state" / "lease.json"
        store = candidate.LeaseStore(path)
        check(store.holder(0) is None, "empty store has a holder")
        check(store.acquire("alice", 10, 5) is True, "initial acquire failed")
        check(store.holder(10) == "alice", "owner missing immediately after acquire")
        check(store.acquire("bob", 14, 10) is False, "active lease was stolen")
        before = path.read_text()
        check(store.renew("bob", 14, 10) is False, "non-owner renewed lease")
        check(path.read_text() == before, "failed renewal modified storage")
        check(store.renew("alice", 14, 6) is True, "owner renewal failed")
        check(json.loads(path.read_text()) == {"owner": "alice", "expires_at": 20}, "renewal expiry mismatch")
        check(candidate.LeaseStore(path).holder(19) == "alice", "lease did not persist")
        check(store.holder(20) is None, "expiry equality must be expired")
        before = path.read_text()
        check(store.renew("alice", 20, 5) is False, "expired lease renewed")
        check(path.read_text() == before, "expired renewal modified storage")
        check(store.acquire("bob", 20, 4) is True, "acquire at expiry boundary failed")
        check(store.holder(23) == "bob" and store.holder(24) is None, "replacement lease boundary mismatch")

        invalid = [("", 1, 2), ("alice", -1, 2), ("alice", 1, 0), ("alice", True, 2), ("alice", 1, True)]
        snapshot = path.read_text()
        for owner, now, ttl in invalid:
            check(store.acquire(owner, now, ttl) is False, f"invalid acquire accepted: {(owner, now, ttl)}")
            check(path.read_text() == snapshot, "invalid acquire modified storage")

        os.environ["LEASE_MODEL_URL"] = "http://127.0.0.1:9/should-not-be-called"
        offline = candidate.LeaseStore(Path(temp) / "offline.json")
        check(offline.acquire("offline", 1, 2) is True, "exact lease depends on external model access")

    print("claim-lease verifier: PASS")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "/app"))
