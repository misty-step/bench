#!/usr/bin/env python3
"""Deterministic source-behavior grader for hydration-safe device state."""
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
    source = Path(sys.argv[1]) / "apps/web/components/library/empty-state.tsx"
    text = source.read_text(encoding="utf-8")
    required = {
        "external-store-import": "useSyncExternalStore",
        "device-hook": "function useCaptureDevice(): CaptureDevice",
        "server-desktop": "() => 'desktop' as CaptureDevice",
        "browser-device": "detectCaptureDevice(window.navigator.userAgent, window.navigator.maxTouchPoints ?? 0)",
        "hydration-lane": "const device = useCaptureDevice();",
    }
    for check, marker in required.items():
        if marker not in text:
            fail(check, f"missing required implementation marker: {marker}")
    if "const [device] = useState<CaptureDevice>(() =>" in text:
        fail("render-time-device", "device detection still runs in the render initializer")
    if "typeof window === 'undefined'" in text:
        fail("render-time-device", "render-time window branching remains")
    if text.count("useSyncExternalStore(") != 1:
        fail("device-hook", "device state must use exactly one external-store subscription")
    print(json.dumps({"passed": True, "checks": sorted(required)}, sort_keys=True))


if __name__ == "__main__":
    main()
