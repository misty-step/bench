#!/usr/bin/env python3
"""Offline executable grader for hydration-safe device state."""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile


def fail(check: str, detail: str) -> None:
    print(json.dumps({"passed": False, "failed_check": check, "detail": detail}, sort_keys=True))
    raise SystemExit(1)


def extract_function(text: str, name: str) -> str | None:
    match = re.search(rf"\bfunction\s+{re.escape(name)}\s*\(", text)
    if match is None:
        return None
    opening = text.find("{", match.end())
    if opening < 0:
        return None
    depth = 0
    quote: str | None = None
    escaped = False
    line_comment = False
    block_comment = False
    index = opening
    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""
        if line_comment:
            if char == "\n":
                line_comment = False
        elif block_comment:
            if char == "*" and next_char == "/":
                block_comment = False
                index += 1
        elif quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in "'\"`":
            quote = char
        elif char == "/" and next_char == "/":
            line_comment = True
            index += 1
        elif char == "/" and next_char == "*":
            block_comment = True
            index += 1
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[match.start() : index + 1]
        index += 1
    return None


def imported_external_store(text: str) -> str | None:
    for match in re.finditer(r"(?ms)^[ \t]*import\b(?P<clause>[^;]*?)\bfrom\s*['\"]react['\"]\s*;", text):
        named = re.search(r"\{([^}]*)\}", match.group("clause"), re.S)
        if named is None:
            continue
        for item in named.group(1).split(","):
            binding = re.fullmatch(r"\s*useSyncExternalStore(?:\s+as\s+(\w+))?\s*", item)
            if binding:
                return binding.group(1) or "useSyncExternalStore"
    return None



ORACLE_PREFIX = r'''
type CaptureDevice = 'ios' | 'android' | 'desktop';
const isIosBrowser = (userAgent: string, maxTouchPoints = 0): boolean =>
  /iPad|iPhone|iPod/i.test(userAgent) || (/Macintosh/i.test(userAgent) && maxTouchPoints > 1);
'''

ORACLE_SUFFIX = r'''
const observed = useCaptureDevice();
if (observed.server !== 'desktop' || observed.client !== 'android') {
  throw new Error(`hydration snapshots were ${JSON.stringify(observed)}`);
}
if (detectCaptureDevice('Mozilla/5.0 (iPhone)', 0) !== 'ios') throw new Error('iOS detection failed');
if (detectCaptureDevice('Mozilla/5.0 (Android)', 0) !== 'android') throw new Error('Android detection failed');
if (detectCaptureDevice('Mozilla/5.0 (Macintosh)', 0) !== 'desktop') throw new Error('desktop detection failed');
'''


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: grader.py REPOSITORY")
    source = Path(sys.argv[1]).resolve() / "apps/web/components/library/empty-state.tsx"
    if not source.is_file():
        fail("invalid-syntax", "target TSX source is missing")
    text = source.read_text(encoding="utf-8")
    external_store_name = imported_external_store(text)
    detect = extract_function(text, "detectCaptureDevice")
    hook = extract_function(text, "useCaptureDevice")
    capture = extract_function(text, "CaptureSurfaces")
    if detect is None:
        fail("external-store-import", "device classification is missing")
    if hook is None:
        check = "device-hook" if external_store_name is not None else "external-store-import"
        fail(check, "external-store hook is missing")
    if external_store_name is None:
        if re.search(r"\buseSyncExternalStore\s*\(", hook) is not None:
            fail("device-hook", "useCaptureDevice calls an external-store hook without its production import")
        fail("external-store-import", "production source does not import useSyncExternalStore from react")
    if re.search(rf"\b{re.escape(external_store_name)}\s*\(", hook) is None:
        fail("device-hook", "useCaptureDevice does not call the imported external-store hook")
    if capture is None or re.search(r"\buseCaptureDevice\s*\(", re.sub(r"/\*.*?\*/|//[^\n]*", "", capture, flags=re.S)) is None:
        fail("render-path", "CaptureSurfaces does not invoke useCaptureDevice on its render path")
    with tempfile.TemporaryDirectory(prefix="harness-census-ts-") as temporary:
        root = Path(temporary)
        candidate = root / "candidate.ts"
        compiled = root / "candidate.js"
        candidate.write_text(
            ORACLE_PREFIX
            + detect
            + "\nconst noopSubscribe = () => () => {};\n"
            + f"const {external_store_name} = (_subscribe: unknown, getSnapshot: () => CaptureDevice, getServerSnapshot: () => CaptureDevice) => {{\n"
            + "  const server = getServerSnapshot();\n"
            + "  delete (globalThis as { window?: unknown }).window;\n"
            + "  (globalThis as { window?: unknown }).window = { navigator: { userAgent: 'Mozilla/5.0 (Android)', maxTouchPoints: 0 } };\n"
            + "  return { server, client: getSnapshot() };\n"
            + "};\n"
            + hook
            + ORACLE_SUFFIX,
            encoding="utf-8",
        )
        syntax = subprocess.run(
            ["bun", "build", "--target", "browser", "--outfile", str(compiled), str(source), "--external=*"],
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
        if syntax.returncode:
            fail("invalid-syntax", (syntax.stdout + syntax.stderr)[-4000:])
        result = subprocess.run(["bun", "run", str(candidate)], text=True, capture_output=True, timeout=120, check=False)
        if result.returncode:
            output = (result.stdout + result.stderr)[-4000:]
            if "hydration snapshots" in output or "window is not defined" in output:
                fail("server-desktop", output)
            fail("device-hook", output)
    print(json.dumps({"passed": True, "checks": ["external-store-import", "device-hook", "server-desktop", "browser-device", "hydration-lane"]}, sort_keys=True))


if __name__ == "__main__":
    main()
