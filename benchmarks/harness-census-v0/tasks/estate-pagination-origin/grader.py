#!/usr/bin/env python3
"""Deterministic source-behavior grader for pagination origin validation."""
from __future__ import annotations

import json
from pathlib import Path
import sys


def fail(check: str, detail: str) -> None:
    print(json.dumps({"passed": False, "failed_check": check, "detail": detail}, sort_keys=True))
    raise SystemExit(1)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: grader.py REPOSITORY")
    text = (Path(sys.argv[1]) / "src/collect/digitalocean.rs").read_text(encoding="utf-8")
    required = {
        "origin-helper": "fn validated_next",
        "relative-path": "next.starts_with('/') && !next.starts_with(\"//\")",
        "scheme-check": "candidate.scheme() == base.scheme()",
        "host-check": "candidate.host_str() == base.host_str()",
        "port-check": "candidate.port_or_known_default() == base.port_or_known_default()",
        "early-rejection": "anyhow::bail!(\"digitalocean pagination next URL is cross-origin\")",
        "pagination-use": "path = validated_next(base, next)?",
        "regression-test": "pagination_rejects_cross_origin_urls_before_a_request",
    }
    for check, marker in required.items():
        if marker not in text:
            fail(check, f"missing required implementation marker: {marker}")
    if text.count("path = validated_next(base, next)?") != 2:
        fail("pagination-use", "both provider pagination loops must validate the next URL")
    print(json.dumps({"passed": True, "checks": sorted(required)}, sort_keys=True))


if __name__ == "__main__":
    main()
