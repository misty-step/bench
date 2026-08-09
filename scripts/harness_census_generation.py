"""Generate frozen worker packages, images, and hidden verifier wrappers."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shutil
import stat
import re
from typing import Mapping

from harness_census_common import (
    BUN_VERSION,
    CARGO_VERSION,
    GO_IMAGE,
    GO_VERSION,
    HARNESSES,
    NODE_IMAGE,
    PACKAGE,
    RUST_IMAGE,
    RUST_VERSION,
    bytes_digest,
    canonical,
    confined_path,
    digest,
    fail,
    tree_digest,
)
_PRIME_FORBIDDEN_NAMES = {".env", ".npmrc", ".yarnrc", ".pnpmrc", "credentials", "credentials.json", "auth.json", "id_rsa", "id_ed25519", "known_hosts"}
_PRIME_SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(rb"\b(?:gh[pousr]|sk)-[A-Za-z0-9_-]{16,}\b"),
)
def _prime_payload(source: Path, metadata: dict[str, object]) -> dict[str, Path]:
    if source.is_symlink() or not source.is_dir():
        fail(f"Prime package directory is unsafe: {source}")
    declared = metadata.get("files", [])
    if declared is None:
        declared = []
    if not isinstance(declared, list) or any(not isinstance(value, str) or not value.strip() for value in declared):
        fail("Prime package package.json files must be a non-empty string list")
    binary = metadata.get("bin", {}).get("prime-agent") if isinstance(metadata.get("bin"), dict) else None
    if not isinstance(binary, str):
        fail("Prime package bin declaration is invalid")
    required = {"package.json", binary, "dist/prime-agent-runtime/pyproject.toml", "dist/prime-agent-runtime/src/rlm/__init__.py"}
    patterns = [*declared, *required]
    if any(any(not part or part in {".", ".."} or part.startswith(".") for part in pattern.rstrip("/").split("/")) for pattern in patterns):
        fail("Prime package contains an unsafe payload declaration")
    files: dict[str, Path] = {}
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source).as_posix()
        if relative not in required and not any(relative == pattern or relative.startswith(pattern.rstrip("/") + "/") for pattern in patterns):
            continue
        parts = relative.split("/")
        if any(not part or part in {".", ".."} or part.startswith(".") for part in parts):
            fail(f"Prime package contains an unsafe path: {relative}")
        if parts[-1].lower() in _PRIME_FORBIDDEN_NAMES:
            fail(f"Prime package contains a credential-like file: {relative}")
        info = os.lstat(path)
        if stat.S_ISLNK(info.st_mode):
            fail(f"Prime package contains a non-regular file: {relative}")
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode):
            fail(f"Prime package contains a non-regular file: {relative}")
        files[relative] = path
    for name in required:
        if name not in files:
            fail(f"Prime package payload is missing: {name}")
    for name, path in files.items():
        if any(pattern.search(path.read_bytes()) for pattern in _PRIME_SECRET_PATTERNS):
            fail(f"Prime package contains a secret-like value: {name}")
    return files


def _prime_payload_digest(files: Mapping[str, Path]) -> str:
    return digest([
        (name, bytes_digest(path.read_bytes()), stat.S_IMODE(os.lstat(path).st_mode))
        for name, path in sorted(files.items())
    ])


def prime_package_info(path: Path) -> dict[str, str]:
    metadata_path = path / "package.json"
    if path.is_symlink() or not path.is_dir() or metadata_path.is_symlink() or not metadata_path.is_file():
        fail(f"Prime package directory is missing or unsafe: {path}")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        fail(f"Prime package metadata is invalid: {error}")
    if not isinstance(metadata, dict) or metadata.get("name") != "prime-agent" or metadata.get("version") != "0.7.0":
        fail("Prime package must be prime-agent version 0.7.0")
    binary = metadata.get("bin", {}).get("prime-agent") if isinstance(metadata.get("bin"), dict) else None
    if binary != "dist/bundle/cli.js":
        fail("Prime package bin must point to dist/bundle/cli.js")
    payload = _prime_payload(path, metadata)
    if not stat.S_IMODE(os.lstat(path / binary).st_mode) & 0o111:
        fail("Prime package CLI must be executable")
    dependency_lock = prime_dependency_lock_info(metadata)
    payload_digest = _prime_payload_digest(payload)
    return {
        "package": "prime-agent@0.7.0",
        "version": "0.7.0",
        "source_kind": "operator_supplied_package_with_checked_in_npm_lock",
        "digest": digest({"payload": payload_digest, "dependency_lock": dependency_lock["lock_digest"]}),
        "payload_digest": payload_digest,
        "dependency_lock_digest": dependency_lock["lock_digest"],
        "dependency_lock_path": dependency_lock["path"],
    }


def stage_prime_package(root: Path, source: Path) -> dict[str, str]:
    info = prime_package_info(source)
    payload = _prime_payload(source, json.loads((source / "package.json").read_text(encoding="utf-8")))
    destination = confined_path(root, "packages", f"prime-agent-{info['digest'][:16]}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        fail(f"staged Prime package destination already exists: {destination}")
    destination.mkdir()
    for name, source_path in payload.items():
        target = confined_path(destination, *name.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target)
    dependency_lock = Path(info["dependency_lock_path"]) / "package-lock.json"
    shutil.copy2(dependency_lock, destination / "package-lock.json")
    if _prime_payload_digest({name: confined_path(destination, *name.split("/")) for name in payload}) != info["payload_digest"]:
        fail("staged Prime package payload digest changed")
    if bytes_digest((destination / "package-lock.json").read_bytes()) != info["dependency_lock_digest"]:
        fail("staged Prime package dependency lock digest changed")
    if not stat.S_IMODE(os.lstat(destination / "dist/bundle/cli.js").st_mode) & 0o111:
        fail("staged Prime package CLI is not executable")
    return {**info, "path": str(destination)}

def locked_package_info(
    path: Path,
    expected: dict[str, str],
    label: str,
    *,
    expected_optional: dict[str, str] | None = None,
    expected_name: str | None = None,
    expected_version: str | None = None,
) -> dict[str, str]:
    metadata_path, lock_path = path / "package.json", path / "package-lock.json"
    if not metadata_path.is_file() or not lock_path.is_file():
        fail(f"locked package is missing for {label}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("private") is not True or metadata.get("dependencies") != expected:
        fail(f"locked package dependencies are invalid for {label}")
    if expected_optional is not None and metadata.get("optionalDependencies", {}) != expected_optional:
        fail(f"locked package optional dependencies are invalid for {label}")
    if expected_name is not None and metadata.get("name") != expected_name:
        fail(f"locked package name is invalid for {label}")
    if expected_version is not None and metadata.get("version") != expected_version:
        fail(f"locked package version is invalid for {label}")
    lock_bytes = lock_path.read_bytes()
    lock = json.loads(lock_bytes)
    root = lock.get("packages", {}).get("", {})
    if lock.get("lockfileVersion") != 3 or root.get("dependencies") != expected:
        fail(f"package lock does not bind the declared dependencies for {label}")
    if expected_optional is not None and root.get("optionalDependencies", {}) != expected_optional:
        fail(f"package lock does not bind the optional dependencies for {label}")
    if expected_name is not None and (lock.get("name") != expected_name or root.get("name") != expected_name):
        fail(f"package lock does not bind the name for {label}")
    if expected_version is not None and (lock.get("version") != expected_version or root.get("version") != expected_version):
        fail(f"package lock does not bind the version for {label}")
    unpinned = [
        name
        for name, value in lock.get("packages", {}).items()
        if name and isinstance(value, dict) and not value.get("link") and not value.get("integrity")
    ]
    if unpinned:
        fail(f"package lock has entries without integrity for {label}: {unpinned}")
    return {"digest": tree_digest(path, exclude_git=False), "lock_digest": bytes_digest(lock_bytes), "path": str(path)}


def prime_dependency_lock_info(metadata: dict[str, object]) -> dict[str, str]:
    dependencies = metadata.get("dependencies")
    optional = metadata.get("optionalDependencies", {})
    if (
        not isinstance(dependencies, dict)
        or not isinstance(optional, dict)
        or any(not isinstance(key, str) or not isinstance(value, str) for key, value in dependencies.items())
        or any(not isinstance(key, str) or not isinstance(value, str) for key, value in optional.items())
    ):
        fail("Prime package dependencies are invalid")
    return locked_package_info(
        PACKAGE / "packages" / "prime",
        dependencies,
        "Prime runtime",
        expected_optional=optional,
        expected_name="prime-agent",
        expected_version="0.7.0",
    )


def runtime_package_info(harness: str) -> dict[str, str]:
    spec = HARNESSES[harness]
    path = PACKAGE / "packages" / harness
    expected = {spec.package.rsplit("@", 1)[0]: spec.version, "bun": BUN_VERSION, "pnpm": "10.22.0"}
    return {
        "package": spec.package,
        "version": spec.version,
        "source_kind": "checked_in_npm_lock",
        **locked_package_info(path, expected, harness),
    }


def node_toolchain_package_info() -> dict[str, str]:
    expected = {"bun": BUN_VERSION, "pnpm": "10.22.0"}
    return locked_package_info(PACKAGE / "packages" / "node-toolchain", expected, "Node toolchain")


def harness_package_info(harness: str, prime_package: dict[str, str] | None) -> dict[str, str]:
    if harness != "prime":
        return runtime_package_info(harness)
    if prime_package is None:
        fail("Prime package metadata is missing")
    toolchain = node_toolchain_package_info()
    return {
        **prime_package,
        "digest": digest({"prime": prime_package["digest"], "node_toolchain": toolchain["digest"]}),
        "prime_digest": prime_package["digest"],
        "node_toolchain_path": toolchain["path"],
    }




def dockerfile(harness: str, package_name: str, task_id: str | None = None) -> str:
    spec = HARNESSES[harness]
    task_kind = "go" if task_id and task_id.startswith("iron-forest-") else "rust" if task_id and task_id.startswith("estate-") else "typescript"
    if task_kind == "go":
        base = (
            f"FROM {GO_IMAGE} AS go-toolchain\n"
            f"FROM {NODE_IMAGE}\n"
            "COPY --from=go-toolchain /usr/local/go /usr/local/go\n"
            "COPY --from=go-toolchain /go /go\n"
            "ENV PATH=/usr/local/go/bin:/go/bin:${PATH}\n"
            "WORKDIR /workspace\n"
            "RUN node --version | grep -Eq '^v(22\\.(19|[2-9][0-9])\\.|2[3-9]\\.)'\n"
            f"RUN go version | grep -F 'go{GO_VERSION}'\n"
        )
        toolchain_labels = f'LABEL org.misty-step.toolchain.go="{GO_VERSION}"\n'
    elif task_kind == "rust":
        base = (
            f"FROM {RUST_IMAGE} AS rust-toolchain\n"
            f"FROM {NODE_IMAGE}\n"
            "COPY --from=rust-toolchain /usr/local/cargo /usr/local/cargo\n"
            "COPY --from=rust-toolchain /usr/local/rustup /usr/local/rustup\n"
            "ENV CARGO_HOME=/usr/local/cargo RUSTUP_HOME=/usr/local/rustup "
            "PATH=/usr/local/cargo/bin:/usr/local/rustup/toolchains/" + RUST_VERSION + "-x86_64-unknown-linux-gnu/bin:${PATH}\n"
            "WORKDIR /workspace\n"
            "RUN node --version | grep -Eq '^v(22\\.(19|[2-9][0-9])\\.|2[3-9]\\.)'\n"
            f"RUN rustc --version | grep -F 'rustc {RUST_VERSION}' && cargo --version | grep -F 'cargo {CARGO_VERSION}'\n"
        )
        toolchain_labels = f'LABEL org.misty-step.toolchain.rustc="{RUST_VERSION}"\nLABEL org.misty-step.toolchain.cargo="{CARGO_VERSION}"\n'
    else:
        base = (
            f"FROM {NODE_IMAGE}\n"
            "WORKDIR /workspace\n"
            "RUN node --version | grep -Eq '^v(22\\.(19|[2-9][0-9])\\.|2[3-9]\\.)'\n"
        )
        toolchain_labels = f'LABEL org.misty-step.toolchain.bun="{BUN_VERSION}"\nLABEL org.misty-step.toolchain.pnpm="10.22.0"\n'
    packages = "python3 ca-certificates unzip git patch"
    if task_kind == "rust":
        packages += " build-essential"
    if harness == "prime":
        packages += " bubblewrap coreutils ipython3 python3-pip"
    install = f"RUN apt-get update && apt-get install -y --no-install-recommends {packages} && rm -rf /var/lib/apt/lists/*\n"
    labels = f'LABEL org.misty-step.harness="{harness}"\nLABEL org.misty-step.agent-package="{spec.package}"\n' + toolchain_labels
    if harness == "prime":
        install += f"COPY runtime-package/ /opt/node-toolchain/\nRUN cd /opt/node-toolchain && npm ci --omit=dev\nRUN /opt/node-toolchain/node_modules/.bin/bun --version | grep -Fx '{BUN_VERSION}' && /opt/node-toolchain/node_modules/.bin/pnpm --version | grep -Fx '10.22.0'\nCOPY {package_name}/ /opt/prime-agent/\nRUN test -x /opt/prime-agent/dist/bundle/cli.js\nRUN cd /opt/prime-agent && npm ci --omit=dev\nRUN python3 -m pip install --break-system-packages /opt/prime-agent/dist/prime-agent-runtime\nRUN python3 -c 'import ipykernel, rlm; assert callable(rlm.run)'\nRUN python3 -c 'import IPython'\nRUN node -e 'const p=require(\"/opt/prime-agent/package.json\"); if(p.name!==\"prime-agent\"||p.version!==\"0.7.0\"||p.bin?.[\"prime-agent\"]!==\"dist/bundle/cli.js\") process.exit(1)'\nRUN /opt/prime-agent/dist/bundle/cli.js --version 2>&1 | grep -F '0.7.0'\nRUN ln -sf /opt/prime-agent/dist/bundle/cli.js /usr/local/bin/prime-agent && ln -sf /usr/local/bin/prime-agent /usr/local/bin/prime\n"
        path = "/opt/node-toolchain/node_modules/.bin:/opt/prime-agent/node_modules/.bin:/usr/local/bin:${PATH}"
    else:
        binary = "omp" if harness == "omp" else "pi"
        install += f"COPY {package_name}/ /opt/harness/\nRUN cd /opt/harness && npm ci --omit=dev\nRUN /opt/harness/node_modules/.bin/bun --version | grep -Fx '{BUN_VERSION}' && /opt/harness/node_modules/.bin/pnpm --version | grep -Fx '10.22.0'\nRUN ln -sf /opt/harness/node_modules/.bin/{binary} /usr/local/bin/{binary}\n"
        path = "/opt/harness/node_modules/.bin:${PATH}"
    dependencies = "COPY repo/ /workspace/\n"
    if task_kind == "go":
        dependencies += "RUN cd /workspace && GOTOOLCHAIN=local GOPROXY=https://proxy.golang.org GOSUMDB=sum.golang.org go mod download\nENV GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off GOMODCACHE=/root/go/pkg/mod GOCACHE=/tmp/go-cache\n"
    elif task_kind == "rust":
        dependencies += "RUN cd /workspace && CARGO_NET_OFFLINE=false cargo fetch --locked\nENV CARGO_NET_OFFLINE=true CARGO_TERM_COLOR=never CARGO_TARGET_DIR=/tmp/cargo-target\n"
    else:
        dependencies += f"RUN bun --version | grep -Fx '{BUN_VERSION}' && pnpm --version | grep -Fx '10.22.0'\nRUN cd /workspace && pnpm install --frozen-lockfile\nENV BUN_INSTALL_CACHE_DIR=/tmp/bun-cache\n"
    return base + install + labels + f'ENV PATH="{path}"\n' + dependencies


def verifier_source(grader: Path, source_manifest: dict[str, str], allowed_paths: tuple[str, ...]) -> str:
    grader_encoded = base64.b64encode(grader.read_bytes()).decode("ascii")
    manifest_encoded = base64.b64encode(canonical({"files": source_manifest, "allowed_paths": list(allowed_paths)})).decode("ascii")
    return f'''#!/usr/bin/env python3
"""Campaign-mounted grader and hidden source-scope verifier."""
from __future__ import annotations
import base64
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
GRADER = base64.b64decode({grader_encoded!r})
MANIFEST = json.loads(base64.b64decode({manifest_encoded!r}))
LOG_DIR = Path(os.environ["HARNESS_CENSUS_LOG_DIR"])
def files(root):
    result = {{}}
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            value = b"SYMLINK:" + path.readlink().as_posix().encode()
        elif path.is_file():
            value = path.read_bytes()
        else:
            continue
        result[name] = hashlib.sha256(value).hexdigest()
    return result
def reward(payload, reward_value, status):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    passed_checks = payload.get("passed_checks", 0)
    total_checks = payload.get("total_checks", 1)
    task_points = payload.get("task_points", reward_value)
    hard_pass = payload.get("hard_pass", payload.get("passed") is True and task_points == 1.0)
    if isinstance(passed_checks, bool) or not isinstance(passed_checks, int) or isinstance(total_checks, bool) or not isinstance(total_checks, int) or total_checks <= 0 or passed_checks < 0 or passed_checks > total_checks or isinstance(task_points, bool) or not isinstance(task_points, (int, float)) or task_points != passed_checks / total_checks or not 0.0 <= float(task_points) <= 1.0:
        passed_checks, total_checks, task_points, hard_pass = 0, 1, 0.0, False
    hard_pass = bool(hard_pass) and passed_checks == total_checks and float(task_points) == 1.0
    binary_reward = 1.0 if hard_pass else 0.0
    report = {{"schema_version": "harness_census.grader_report.v1", "reward": binary_reward, "status": status, "passed": hard_pass, "hard_pass": hard_pass, "passed_checks": passed_checks, "total_checks": total_checks, "task_points": binary_reward, "grader_report": payload}}
    (LOG_DIR / "reward.json").write_text(json.dumps({{"reward": binary_reward}}) + "\\n", encoding="utf-8")
    (LOG_DIR / "grader-report.json").write_text(json.dumps(report, sort_keys=True) + "\\n", encoding="utf-8")
def scope_check(workspace):
    before = MANIFEST["files"]
    after = files(workspace)
    added = sorted(set(after) - set(before))
    deleted = sorted(set(before) - set(after))
    changed = sorted(name for name in set(before) & set(after) if before[name] != after[name])
    outside = sorted(name for name in changed if name not in MANIFEST["allowed_paths"])
    root = workspace.resolve()
    unsafe = sorted(
        name
        for name in MANIFEST["allowed_paths"]
        if (workspace / name).is_symlink() or not (workspace / name).resolve().is_relative_to(root)
    )
    if added or deleted or outside or unsafe:
        reward({{"passed": False, "hard_pass": False, "passed_checks": 0, "total_checks": 1, "task_points": 0.0, "failed_check": "scope", "added_paths": added, "deleted_paths": deleted, "changed_outside_allowed_paths": outside, "unsafe_allowed_paths": unsafe}}, 0.0, "scope_failure")
        return False
    return True
def main():
    if len(sys.argv) != 2:
        reward({{"passed": False, "hard_pass": False, "passed_checks": 0, "total_checks": 1, "task_points": 0.0, "failed_check": "invalid-arguments"}}, 0.0, "quality_failure")
        raise SystemExit(2)
    workspace = Path(sys.argv[1])
    if not scope_check(workspace):
        raise SystemExit(1)
    namespace = {{"__name__": "embedded_grader"}}
    exec(compile(GRADER, "embedded-grader.py", "exec"), namespace)
    output = io.StringIO()
    code = 1
    with contextlib.redirect_stdout(output):
        try:
            sys.argv = ["embedded-grader.py", str(workspace)]
            namespace["main"]()
            code = 0
        except SystemExit as error:
            code = int(error.code) if isinstance(error.code, int) else 1
        except Exception as error:
            print(json.dumps({{"passed": False, "hard_pass": False, "passed_checks": 0, "total_checks": 1, "task_points": 0.0, "failed_check": "grader-exception", "detail": f"{{type(error).__name__}}: {{error}}"}}))
    lines = [line for line in output.getvalue().splitlines() if line.strip()]
    try:
        report = json.loads(lines[-1]) if lines else {{"passed": False, "failed_check": "no-report"}}
    except json.JSONDecodeError:
        report = {{"passed": False, "hard_pass": False, "passed_checks": 0, "total_checks": 1, "task_points": 0.0, "failed_check": "invalid-report"}}
    passed_checks = report.get("passed_checks", 0)
    total_checks = report.get("total_checks", 1)
    task_points = report.get("task_points", 0.0)
    hard_pass = code == 0 and report.get("passed") is True and passed_checks == total_checks and task_points == 1.0
    reward(report, float(task_points) if isinstance(task_points, (int, float)) and not isinstance(task_points, bool) else 0.0, "success" if hard_pass else "quality_failure")
    print(json.dumps(report, sort_keys=True))
    raise SystemExit(0 if hard_pass else 1)
if __name__ == "__main__":
    main()
'''
