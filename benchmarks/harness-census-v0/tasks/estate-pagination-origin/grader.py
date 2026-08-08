#!/usr/bin/env python3
"""Offline behavioral grader for pagination origin validation."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


def fail(check: str, detail: str) -> None:
    print(json.dumps({"passed": False, "failed_check": check, "detail": detail}, sort_keys=True))
    raise SystemExit(1)


def extract_function(text: str, name: str) -> str | None:
    match = re.search(rf"\b(?:async\s+)?fn\s+{re.escape(name)}\s*\(", text)
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


def has_pagination_validation(body: str) -> bool:
    extractions = list(re.finditer(r"\.\s*next\b", body))
    if not extractions:
        return False
    for index, extraction in enumerate(extractions):
        end = extractions[index + 1].start() if index + 1 < len(extractions) else len(body)
        segment = body[extraction.end() : end]
        call = re.search(r"\bvalidated_next\s*\([^;{}]*\bnext\b[^;{}]*\)", segment)
        if call is None:
            return False
        statement_start = max(segment.rfind(";", 0, call.start()), segment.rfind("{", 0, call.start()), segment.rfind("}", 0, call.start()))
        statement_end = segment.find(";", call.end())
        if statement_end < 0:
            statement_end = len(segment)
        statement = segment[statement_start + 1 : statement_end]
        if re.search(r"\bpath\s*=", statement):
            continue
        binding = re.search(r"\b(?:let|const|var)\s+(\w+)\s*=\s*validated_next\b", statement)
        if binding is None or re.search(rf"\bpath\s*=\s*{re.escape(binding.group(1))}\b", segment[call.end() :]) is None:
            return False
    return True




ORACLE = r'''

#[cfg(test)]
mod harness_census_pagination_oracle {
    #[test]
    fn validates_relative_and_exact_origin_links() {
        let base = "https://api.digitalocean.com";
        assert_eq!(
            super::validated_next(base, "/v2/apps?page=2".into()).unwrap(),
            "/v2/apps?page=2"
        );
        assert!(super::validated_next(
            base,
            "https://api.digitalocean.com/v2/apps?page=2".into()
        )
        .is_ok());
        for hostile in [
            "https://attacker.invalid/steal",
            "//attacker.invalid/steal",
            "http://api.digitalocean.com/v2/apps?page=2",
            "https://api.digitalocean.com:8443/v2/apps?page=2",
        ] {
            assert!(
                super::validated_next(base, hostile.into()).is_err(),
                "accepted hostile pagination link: {hostile}"
            );
        }
    }
}
'''


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: grader.py REPOSITORY")
    repo = Path(sys.argv[1]).resolve()
    source = repo / "src" / "collect" / "digitalocean.rs"
    if not source.is_file() or not (repo / "Cargo.toml").is_file():
        fail("invalid-syntax", "target Rust source or Cargo manifest is missing")
    try:
        text = source.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        fail("invalid-syntax", str(error))
    if extract_function(text, "validated_next") is None:
        fail("origin-helper", "validated_next helper is missing")
    for function_name in ("fetch_droplets", "fetch_apps"):
        body = extract_function(text, function_name)
        if body is None or not has_pagination_validation(body):
            fail("pagination-use", f"{function_name} does not validate every pagination next link")
    original = source.read_bytes()
    try:
        source.write_bytes(original + ORACLE.encode("utf-8"))
        env = os.environ.copy()
        env.update({"CARGO_NET_OFFLINE": "true", "CARGO_TERM_COLOR": "never"})
        with tempfile.TemporaryDirectory(prefix="harness-census-cargo-") as target:
            env["CARGO_TARGET_DIR"] = target
            result = subprocess.run(
                ["cargo", "test", "--offline", "harness_census_pagination_oracle", "--", "--nocapture"],
                cwd=repo,
                env=env,
                text=True,
                capture_output=True,
                timeout=45,
                check=False,
            )
    except subprocess.TimeoutExpired as error:
        fail("setup-timeout", f"offline Rust probe exceeded its deterministic timeout: {error}")
    except (OSError, subprocess.SubprocessError) as error:
        fail("invalid-syntax", str(error))
    finally:
        source.write_bytes(original)
    if result.returncode:
        output = (result.stdout + result.stderr)[-5000:]
        if "accepted hostile pagination link" in output:
            fail("scheme-check", output)
        if "could not find" in output or "cannot find function" in output:
            fail("origin-helper", output)
        fail("invalid-syntax", output)
    print(json.dumps({"passed": True, "checks": ["relative-path", "scheme-check", "host-check", "port-check", "pagination-use"]}, sort_keys=True))


if __name__ == "__main__":
    main()
