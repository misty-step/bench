#!/usr/bin/env python3
"""Offline executable grader for hydration-safe device state."""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile


CHECKS = ("hydration-snapshot", "desktop-server-lane", "android-device", "ios-device", "ipad-device", "desktop-device", "render-path", "semantic-lanes", "desktop-surface")


def fail(check: str, detail: str, passed_checks: int = 0) -> None:
    total_checks = len(CHECKS)
    print(json.dumps({"passed": False, "hard_pass": False, "passed_checks": passed_checks, "total_checks": total_checks, "task_points": passed_checks / total_checks, "failed_check": check, "detail": detail}, sort_keys=True))
    raise SystemExit(1)


def executable_source(text: str) -> tuple[str, list[str]]:
    """Remove module edges while retaining the candidate's executable component."""
    exported = re.findall(r"\bexport\s+(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(", text)
    text = re.sub(r"(?m)^[ \t]*['\"]use client['\"];?[ \t]*\n?", "", text, count=1)
    text = re.sub(r"(?ms)^[ \t]*import(?:\s+type)?\b.*?;[ \t]*(?:\n|$)", "", text)
    text = re.sub(r"\bexport\s+(?=(?:async\s+)?function|const|let|var|class)\b", "", text)
    text = re.sub(r"(?ms)^[ \t]*export\s+type\b.*?;[ \t]*(?:\n|$)", "", text)
    return text, exported


ORACLE_PREFIX = r'''
const __state = {
  phase: 'server',
  userAgent: '',
  touchPoints: 0,
  hooks: [],
  cursor: 0,
  effects: [],
  collectEffects: true,
  dirty: false,
  externalStoreCalls: 0,
};
function __window(present, userAgent, touchPoints) {
  if (present) {
    globalThis.window = { navigator: { userAgent, maxTouchPoints: touchPoints } };
  } else {
    delete globalThis.window;
  }
}
function useState(initial) {
  const index = __state.cursor++;
  if (!(index in __state.hooks)) {
    __state.hooks[index] = typeof initial === 'function' ? initial() : initial;
  }
  const setValue = (next) => {
    const value = typeof next === 'function' ? next(__state.hooks[index]) : next;
    if (!Object.is(value, __state.hooks[index])) {
      __state.hooks[index] = value;
      __state.dirty = true;
    }
  };
  return [__state.hooks[index], setValue];
}
function useRef(value) {
  const index = __state.cursor++;
  if (!(index in __state.hooks)) __state.hooks[index] = { current: value };
  return __state.hooks[index];
}
function useCallback(callback) {
  __state.cursor++;
  return callback;
}
function useEffect(effect) {
  __state.cursor++;
  if (__state.collectEffects) __state.effects.push(effect);
}
function useLayoutEffect(effect) { useEffect(effect); }
function useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot) {
  __state.cursor++;
  __state.externalStoreCalls++;
  return __state.phase === 'server' || __state.phase === 'hydrate'
    ? getServerSnapshot()
    : getSnapshot();
}
const React = {
  Fragment: Symbol('Fragment'),
  createElement(type, props, ...children) {
    const nextProps = { ...(props || {}), children: children.length === 1 ? children[0] : children };
    if (typeof type === 'function') return type(nextProps);
    return { type, props: nextProps, children };
  },
};
function cn(...values) { return values.filter(Boolean).join(' '); }
function trackEmptyStateRender() {}
function useRouter() { return { push() {} }; }
function usePwaInstallPrompt() {
  return { installable: false, installed: false, requiresManualInstall: false, promptInstall() {} };
}
function isIosBrowser(userAgent, maxTouchPoints = 0) {
  return /iPad|iPhone|iPod/i.test(userAgent) || (/Macintosh/i.test(userAgent) && maxTouchPoints > 1);
}
function logger() {}
logger.logError = () => {};
logger.logInfo = () => {};
function Button(props) { return React.createElement('button', props, props.children); }
function Link(props) { return React.createElement('a', props, props.children); }
function MemeCell(props) { return React.createElement('div', props, props.children); }
function StickerTab(props) { return React.createElement('div', props, props.children); }
function __text(value) {
  if (value == null || typeof value === 'boolean') return '';
  if (typeof value === 'string' || typeof value === 'number') return String(value);
  if (Array.isArray(value)) return value.map(__text).join('');
  if (typeof value === 'object') return __text(value.children);
  return '';
}
function __render(name, phase, userAgent, touchPoints, runEffects) {
  __state.phase = phase;
  __state.userAgent = userAgent;
  __state.touchPoints = touchPoints;
  __window(phase !== 'server', userAgent, touchPoints);
  __state.hooks = [];
  __state.cursor = 0;
  __state.effects = [];
  __state.collectEffects = true;
  __state.dirty = false;
  __state.externalStoreCalls = 0;
  try {
    let tree = __exports[name]({ variant: 'first-use', showUploadButton: false });
    let text = __text(tree);
    if (runEffects) {
      const effects = __state.effects.slice();
      __state.effects = [];
      for (const effect of effects) effect();
      if (__state.dirty) {
        __state.dirty = false;
        __state.cursor = 0;
        __state.collectEffects = false;
        tree = __exports[name]({ variant: 'first-use', showUploadButton: false });
        text = __text(tree);
      }
    }
    return { text, externalStoreCalls: __state.externalStoreCalls };
  } catch (error) {
    return { error: String(error && error.message ? error.message : error), text: '', externalStoreCalls: __state.externalStoreCalls };
  }
}
function __hasLane(text) {
  return text.includes('chrome extension') || text.includes('share sheet') || text.includes('iphone shortcut');
}
'''


ORACLE_SUFFIX = r'''
const __rootCandidates = Object.keys(__exports);
let __root = null;
let __serverError = null;
for (const candidate of __rootCandidates) {
  const probe = __render(candidate, 'server', 'Mozilla/5.0 (Android)', 0, false);
  if (__hasLane(probe.text)) {
    __root = candidate;
    break;
  }
  if (probe.error && __serverError === null) __serverError = { candidate, error: probe.error };
}
if (__root === null && __serverError !== null) __root = __serverError.candidate;
if (__root === null) throw new Error('capture surface is not reachable from the rendered component');
const __result = {
  root: __root,
  server: __render(__root, 'server', 'Mozilla/5.0 (Android)', 0, false),
  hydrate: __render(__root, 'hydrate', 'Mozilla/5.0 (Android)', 0, false),
  android: __render(__root, 'client', 'Mozilla/5.0 (Android)', 0, true),
  ios: __render(__root, 'client', 'Mozilla/5.0 (iPhone)', 0, true),
  ipad: __render(__root, 'client', 'Mozilla/5.0 (Macintosh)', 2, true),
  desktop: __render(__root, 'client', 'Mozilla/5.0 (Macintosh)', 0, true),
};
console.log(JSON.stringify(__result));
'''


def run_oracle(text: str, exported: list[str]) -> dict[str, object]:
    if not exported:
        fail("render-path", "no exported component is available to exercise")
    exports = ", ".join(f"{name}: {name}" for name in exported)
    body = ORACLE_PREFIX + text + f"\nconst __exports = {{{exports}}};\n" + ORACLE_SUFFIX
    with tempfile.TemporaryDirectory(prefix="harness-census-ts-") as temporary:
        candidate = Path(temporary) / "candidate.tsx"
        candidate.write_text(body, encoding="utf-8")
        runtime = candidate.parent / "node_modules" / "react"
        runtime.mkdir(parents=True)
        (runtime / "package.json").write_text('{"type":"module"}', encoding="utf-8")
        (runtime / "jsx-dev-runtime.js").write_text(
            "export const Fragment = Symbol('Fragment');\n"
            "export function jsxDEV(type, props) {\n"
            "  if (typeof type === 'function') return type(props || {});\n"
            "  const children = props && props.children;\n"
            "  return { type, children: Array.isArray(children) ? children : [children] };\n"
            "}\n",
            encoding="utf-8",
        )
        (runtime / "jsx-runtime.js").write_text(
            "export { Fragment, jsxDEV as jsx } from './jsx-dev-runtime.js';\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            ["bun", "run", str(candidate)],
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
        if result.returncode:
            fail("render-path", (result.stdout + result.stderr)[-4000:])
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        try:
            report = json.loads(lines[-1])
        except (IndexError, json.JSONDecodeError) as error:
            fail("render-path", f"behavior oracle did not return JSON: {error}")
        if not isinstance(report, dict):
            fail("render-path", "behavior oracle returned a non-object report")
        return report


def require_output(report: dict[str, object], key: str, expected: str, check: str) -> None:
    value = report.get(key)
    if not isinstance(value, dict):
        fail(check, f"missing {key} render")
    if value.get("error"):
        detail = str(value["error"])
        if check == "desktop-server-lane" or "window" in detail.lower():
            fail("hydration-snapshot", detail)
    text = str(value.get("text", ""))
    if expected not in text:
        fail(check, f"{key} render did not expose {expected!r}: {text}")


def require_semantic_tokens(source_text: str) -> None:
    lanes = {
        "desktop": ("device === 'desktop'", "chrome extension", "right-click any image, anywhere", "get the extension", "paste / drag", "⌘V or drop files on this page", "SPLOOT_EXTENSION_STORE_URL", "target=\"_blank\""),
        "android": ("device === 'android'", "share sheet", "app installed — share any image to sploot", "install the app once, then share images from anywhere", "browser menu → add to home screen, then share images from anywhere", "paste or drop images here — already live", "wire the share sheet"),
        "ios": ("device === 'ios'", "iphone shortcut", "put sploot in your share sheet — one tap from any app", "set up the shortcut", "home screen", "paste images here — already live", "Link href=\"/app/settings#upload-tokens\""),
    }
    for lane, tokens in lanes.items():
        missing = [token for token in tokens if token not in source_text]
        if missing:
            fail("semantic-lanes", f"{lane} lane is missing semantic tokens or controls: {missing}")
    desktop_tokens = ("SurfaceRow", "Button asChild", "variant=\"primary\"", "get the extension", "paste / drag", "SPLOOT_EXTENSION_STORE_URL")
    missing = [token for token in desktop_tokens if token not in source_text]
    if missing:
        fail("desktop-surface", f"desktop surface changed or lost controls: {missing}")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: grader.py REPOSITORY")
    repo = Path(sys.argv[1]).resolve()
    source = repo / "apps/web/components/library/empty-state.tsx"
    if not source.is_file():
        fail("render-path", "target TSX source is missing")
    source_text = source.read_text(encoding="utf-8")
    require_semantic_tokens(source_text)
    with tempfile.TemporaryDirectory(prefix="harness-census-build-") as temporary:
        syntax = subprocess.run(
            ["bun", "build", "--target", "browser", "--outfile", str(Path(temporary) / "empty-state.js"), str(source), "--external=*"],
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
    if syntax.returncode:
        fail("render-path", (syntax.stdout + syntax.stderr)[-4000:])
    executable, exported = executable_source(source_text)
    report = run_oracle(executable, exported)
    server = report.get("server")
    hydrate = report.get("hydrate")
    if not isinstance(server, dict) or not isinstance(hydrate, dict):
        fail("hydration-snapshot", "hydration renders are missing")
    if server.get("error"):
        fail("desktop-server-lane", str(server["error"]))
    if hydrate.get("error"):
        fail("hydration-snapshot", str(hydrate["error"]))
    server_text = str(server.get("text", ""))
    hydrate_text = str(hydrate.get("text", ""))
    if "chrome extension" not in server_text or "share sheet" in server_text or "iphone shortcut" in server_text:
        fail("desktop-server-lane", f"server render was not the desktop lane: {server_text}")
    if hydrate_text != server_text:
        check = "render-path" if int(hydrate.get("externalStoreCalls", 0)) else "hydration-snapshot"
        fail(check, f"server and hydration renders diverged: {server_text!r} != {hydrate_text!r}")
    require_output(report, "android", "share sheet", "android-device")
    require_output(report, "ios", "iphone shortcut", "ios-device")
    require_output(report, "ipad", "iphone shortcut", "ipad-device")
    require_output(report, "desktop", "chrome extension", "desktop-device")
    total_checks = len(CHECKS)
    print(json.dumps({"passed": True, "hard_pass": True, "passed_checks": total_checks, "total_checks": total_checks, "task_points": 1.0, "checks": list(CHECKS)}, sort_keys=True))


if __name__ == "__main__":
    main()
