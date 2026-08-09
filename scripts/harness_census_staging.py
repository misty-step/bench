"""Stage census tasks and run deterministic, provider-free probes."""
from __future__ import annotations
from dataclasses import replace

import base64
import importlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import re
from typing import Mapping
import sqlite3
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

from harness_census_archive import archive_git_tree
from harness_census_common import (
    AGENT_ALLOWED_HOSTS, BUN_VERSION, CARGO_VERSION, CAMPAIGN_ID, COMPACT_RECEIPT_KEYS, CONTROLLED_EFFORT, CONTROLLED_MODEL,
    CONTROLLED_NETWORK_ENFORCEMENT, CONTROLLED_NETWORK_MODE, CONTROLLED_TASK_NETWORK_ENFORCEMENT,
    CONTROLLED_TRANSPORT_NETWORK_MODE, GO_IMAGE, GO_VERSION, HARBOR_VERSION, HARNESSES, NETWORK_POLICY,
    NATIVE_NETWORK_ENFORCEMENT, NATIVE_NETWORK_MODE, NATIVE_TASK_NETWORK_ENFORCEMENT,
    NATIVE_TRANSPORT_NETWORK_MODE, NODE_IMAGE, RUST_IMAGE, RUST_VERSION,
    Cell, Task, TaskRecord, agent_allowed_hosts_identity_digest, agent_kwargs_identity_digest, bytes_digest, campaign_matrix, campaign_tree_files, cell_stage_digest, cell_summary,
    canonical, canonical_task_set_digest, cohort_identity, confined_path, digest, fail, file_digest, harbor_reward_value, harness_catalog_digest,
    load_tasks, mcp_identity_digest, model_roster_digest, qualification_harness_records, reference_hunk_map_digest, reference_hunk_mapping, row_identity, task_corpus_identity,
    task_identity, tree_digest, tree_files, verified_commit, write_json,
)
from harness_census_gateway import MINT_INTERNAL_BASE_URL, gateway_identity, validate_gateway_contract, write_gateway_assets

QUALIFIER = Path(__file__).resolve().with_name("qualify_harness_census.py")
PACKAGE = Path(__file__).resolve().parents[1] / "benchmarks" / "harness-census-v0"
ROOT = PACKAGE.parents[1]
def ensure_clean_bench_source() -> None:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain=v1", "--untracked-files=all", "--", "scripts", "benchmarks/harness-census-v0"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        fail(f"Bench source status probe failed: {(result.stderr or result.stdout).strip()}")
    dirty = [line[3:] if len(line) >= 4 else line for line in result.stdout.splitlines() if line.strip()]
    if dirty:
        fail(f"Bench source bytes are dirty before stage manifest creation: {', '.join(dirty)}")


def _valid_digest(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)

def _smoke_identity() -> dict[str, object]:
    tasks = load_tasks()
    receipts: dict[str, dict[str, object]] = {}
    for task_id in tasks:
        path = PACKAGE / "receipts" / f"{task_id}.json"
        if not path.is_file():
            fail(f"smoke receipt is missing: {task_id}")
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if receipt.get("task_id") != task_id or receipt.get("qualified") is not True:
            fail(f"smoke receipt is invalid: {task_id}")
        if receipt.get("reference_hunk_map_digest") != reference_hunk_map_digest(tasks[task_id]):
            fail(f"smoke receipt hunk mapping is stale: {task_id}")
        receipts[task_id] = receipt
    task_digest = digest([
        task_identity(
            task,
            str(receipts[task.id]["fixture"]["tree_digest"]),
            file_digest(task.task_dir / "instruction.md"),
            file_digest(task.task_dir / "task.toml"),
            file_digest(task.task_dir / "grader.py"),
            file_digest(task.task_dir / "reference.patch"),
            reference_hunk_map_digest(task),
        )
        for task in tasks.values()
    ])
    pack_manifest = json.loads((PACKAGE / "compositions" / "digests.json").read_text(encoding="utf-8"))
    pack = {name: pack_manifest[name] for name in ("controlled_raw", "controlled_enriched")}
    gateway = gateway_identity()
    return {
        "roster_digest": model_roster_digest(),
        "catalog_digest": harness_catalog_digest(),
        "harness_digest": harness_catalog_digest(),
        "adapter_digest": digest([entry["adapter"] for entry in qualification_harness_records()]),
        "pack_digest": digest(pack),
        "mcp_digest": mcp_identity_digest(),
        "task_digest": task_digest,
        "reference_hunk_map_digest": digest([reference_hunk_map_digest(task) for task in tasks.values()]),
        "grader_digest": digest([receipts[task_id]["reference"]["grader_digest"] for task_id in tasks]),
        "gateway_digests": [gateway["gateway_digest"]],
        "gateway_dockerfile_digests": [gateway["gateway_dockerfile_digest"]],
        "compose_digests": [gateway["compose_digest"]],
    }


def validate_stage_manifest(stage: object, *, stage_id: str) -> None:
    if not isinstance(stage, dict):
        fail(f"{stage_id} stage manifest must be an object")
    schema = json.loads((PACKAGE / "schemas" / "stage-manifest-v1.schema.json").read_text(encoding="utf-8"))
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    missing = sorted(required - set(stage))
    unknown = sorted(set(stage) - set(properties))
    if missing or unknown:
        fail(f"{stage_id} stage manifest keys are invalid: missing={missing} unknown={unknown}")
    for key, rule in properties.items():
        if isinstance(rule, dict) and "const" in rule and key in stage and stage[key] != rule["const"]:
            fail(f"{stage_id} stage manifest field is invalid: {key}")
    if stage.get("campaign_id") != CAMPAIGN_ID or stage.get("stage_id") != stage_id:
        fail(f"{stage_id} stage manifest identity is invalid")
    if stage_id == "campaign" and not _valid_digest(stage.get("worker_preflight_digest")):
        fail("campaign stage manifest worker preflight digest is invalid")
    if stage_id == "campaign":
        cells = stage.get("cells")
        expected_cells = {str(row["cell_id"]) for row in campaign_matrix()}
        if not isinstance(cells, dict) or set(cells) != expected_cells:
            fail("campaign stage manifest cells are incomplete or undeclared")
        for cell_id, entry in cells.items():
            if not isinstance(entry, dict) or not isinstance(entry.get("summary"), dict) or entry["summary"].get("cell_id") != cell_id:
                fail(f"campaign stage manifest cell summary is invalid: {cell_id}")
            summary = entry["summary"]
            for key in ("agent_kwargs_digest", "agent_allowed_hosts_digest", "composition_digest", "adapter_digest", "mcp_digest"):
                if not _valid_digest(summary.get(key)):
                    fail(f"campaign stage manifest cell summary digest is invalid: {cell_id} {key}")
            tasks = entry.get("tasks")
            if not isinstance(tasks, list) or len(tasks) != len(load_tasks()):
                fail(f"campaign stage manifest task set is invalid: {cell_id}")
            for task in tasks:
                required_task_fields = ("task_id", "task_digest", "comparison_task_digest", "reference_hunk_map_digest", "source_cluster", "dockerfile_digest", "gateway_digest", "gateway_dockerfile_digest", "compose_digest", "grader_digest")
                if not isinstance(task, dict) or any(not isinstance(task.get(key), str) or not task[key] for key in required_task_fields):
                    fail(f"campaign stage manifest task identity is invalid: {cell_id}")
    for key in ("roster_digest", "catalog_digest", "harness_digest", "adapter_digest", "pack_digest", "mcp_digest", "task_digest", "reference_hunk_map_digest", "grader_digest", "profile_digest"):
        if not _valid_digest(stage.get(key)):
            fail(f"{stage_id} stage manifest digest is invalid: {key}")
    for key in ("crucible_binary_digest", "prime_package_digest"):
        if stage.get(key) is not None and not _valid_digest(stage.get(key)):
            fail(f"{stage_id} stage manifest digest is invalid: {key}")
    for key in ("dockerfile_digests", "gateway_digests", "gateway_dockerfile_digests", "compose_digests", "package_digests"):
        values = stage.get(key)
        if not isinstance(values, list) or any(not _valid_digest(value) for value in values):
            fail(f"{stage_id} stage manifest digest list is invalid: {key}")
    probe = stage.get("controlled_tool_surface_probe")
    if probe is not None and (not isinstance(probe, dict) or probe.get("status") != "passed" or probe.get("task_network") != "denied_by_tool_and_sandbox" or not isinstance(probe.get("adapters"), list) or len(probe["adapters"]) < 3):
        fail(f"{stage_id} controlled tool surface probe is invalid")
    for field, policy_key in {
        "transport_network_mode": "transport_network_mode",
        "network_enforcement": "network_enforcement",
        "task_network_enforcement": "task_network_enforcement",
    }.items():
        expected = {name: NETWORK_POLICY[name][policy_key] for name in ("controlled", "native_default")}
        if stage.get(field) != expected:
            fail(f"{stage_id} stage manifest network contract is stale: {field}")
        schema_network = properties[field].get("properties", {})
        if {name: schema_network[name].get("const") for name in expected} != expected:
            fail(f"stage manifest schema network contract is stale: {field}")
    if stage.get("retry_policy") != {"product_retry": 0, "transport_retry": 0}:
        fail(f"{stage_id} stage manifest retry policy is invalid")
    decision = stage.get("decision_policy")
    if not isinstance(decision, dict) or decision.get("decision") != "scale_or_repair" or decision.get("task_buckets") != 3 or decision.get("paired_delta_resolvable") != {"point_delta": 1.0} or decision.get("interval_claims") != {"descriptive": True, "inferential": False} or not isinstance(decision.get("forbidden_claims"), list) or not {"winner", "deployment", "context_deletion"}.issubset(decision["forbidden_claims"]) or decision.get("cell_invalidation") != "any_reliability_failure" or decision.get("hard_pass_requires_all_tasks") is not True or decision.get("native_default_separate") is not True:
        fail(f"{stage_id} stage manifest decision policy is invalid")
    if stage_id == "smoke" and any(stage.get(key) != value for key, value in _smoke_identity().items()):
        fail("smoke stage manifest identity is stale")




def require_dir(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_dir():
        fail(f"{label} is missing: {resolved}")
    return resolved


def source_repo(source_root: Path, task: Task) -> Path:
    repository = task.source_repository.rsplit("/", 1)[-1]
    return require_dir(source_root / repository, f"source repository {repository}")


def qualification(source_root: Path) -> None:
    result = subprocess.run([sys.executable, str(QUALIFIER), "--no-smoke", "--source-root", str(source_root)], cwd=QUALIFIER.parent.parent, text=True, capture_output=True, check=False)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip().splitlines()[-1:]
        fail(f"qualification failed: {' '.join(detail)}")


def crucible_identity(path: Path) -> dict[str, str]:
    import re
    result = subprocess.run([str(path), "--version"], text=True, capture_output=True, check=False)
    if result.returncode:
        fail(f"Crucible version probe failed: {(result.stderr or result.stdout).strip()[-500:]}")
    commits = sorted(set(re.findall(r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])", result.stdout + result.stderr)))
    if len(commits) != 1:
        fail("Crucible version output must expose exactly one full commit")
    return {"commit": verified_commit(commits[0], "Crucible commit"), "binary_digest": bytes_digest(path.read_bytes())}


def load_compositions() -> tuple[dict[str, str], dict[str, str]]:
    assets: dict[str, str] = {}
    digests: dict[str, str] = {}
    manifest = json.loads((PACKAGE / "compositions" / "digests.json").read_text(encoding="utf-8"))
    for name in ("controlled_raw", "controlled_enriched"):
        declaration = manifest[name]
        if name == "controlled_enriched" and declaration.get("kind") == "generated_context_pack":
            assets[name] = "generated context pack"
            digests[name] = digest(declaration)
            continue
        path = PACKAGE / "compositions" / declaration["path"]
        actual = file_digest(path)
        if actual != declaration["sha256"]:
            fail(f"composition digest mismatch: {name}")
        assets[name], digests[name] = path.read_text(encoding="utf-8"), actual
    if not assets["controlled_raw"].strip():
        fail("controlled raw composition asset must not be empty")
    return assets, digests


def validate_smoke() -> dict[str, str]:
    path = PACKAGE / "smoke" / "harness-census-v0.json"
    smoke = json.loads(path.read_text(encoding="utf-8"))
    if smoke.get("schema_version") != "harness_census.smoke.v1" or smoke.get("kind") != "staging_manifest" or smoke.get("runnable") is not False:
        fail("smoke artifact is not an explicit non-runnable staging manifest")
    identity = _smoke_identity()
    for key in ("task_digest", "reference_hunk_map_digest", "grader_digest", "pack_digest"):
        if smoke.get(key) != identity[key]:
            fail(f"smoke identity is stale: {key}")
    tasks = load_tasks()
    if smoke.get("task_ids") != list(tasks) or "runner" in smoke or "model" in smoke:
        fail("smoke artifact has an invalid shared runner or task identity")
    cells = smoke.get("cells")
    expected = []
    for row in campaign_matrix():
        expected.append({**row, "task_ids": list(tasks), "identity_digest": digest({"cell": row, "task_digest": identity["task_digest"], "reference_hunk_map_digest": identity["reference_hunk_map_digest"]})})
    if cells != expected:
        fail("smoke cells do not match the canonical nine-cell matrix")
    stage_path = PACKAGE / "smoke" / "stage-manifest.json"
    validate_stage_manifest(json.loads(stage_path.read_text(encoding="utf-8")), stage_id="smoke")
    return {"smoke_digest": bytes_digest(path.read_bytes())}


def task_prompt(task: Task, composition: str, assets: Mapping[str, str], *, context_pack: object | None = None) -> str:
    prompt = (task.task_dir / "instruction.md").read_text(encoding="utf-8").strip()
    if composition == "native_default":
        return prompt + "\n"
    value = prompt + "\n\n" + assets["controlled_raw"].strip()
    if composition == "controlled_enriched":
        if context_pack is None:
            fail("controlled_enriched staging requires its generated context pack")
        value += "\n\n" + getattr(context_pack, "context_bytes").decode("utf-8")
    return value + "\n"


def staged_task_toml(task: Task, composition: str) -> tuple[str, str]:
    import tomllib
    text = (task.task_dir / "task.toml").read_text(encoding="utf-8")
    expected = "public"
    marker = 'network_mode = "public"'
    if marker not in text:
        fail(f"task manifest must declare Harbor public baseline: {task.id}")
    if tomllib.loads(text).get("environment", {}).get("network_mode") != expected:
        fail(f"task manifest baseline network mode is invalid: {task.id}")
    return text, expected



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
def stage_task(cell_dir: Path, task: Task, harness: str, composition: str, assets: Mapping[str, str], source_root: Path, package: dict[str, str]) -> TaskRecord:
    from harness_census_context import prepare_task_pack, raw_skill_digest

    task_dir = cell_dir / "tasks" / task.id
    env, source = task_dir / "environment", task_dir / "environment" / "repo"
    reference_bytes = (task.task_dir / "reference.patch").read_bytes()
    forbidden_tokens = [
        reference_bytes,
        *[task_id.encode("utf-8") for task_id in load_tasks() if task_id != task.id],
    ]
    archive_git_tree(source_repo(source_root, task), task.source_sha, source)
    forbidden_tokens.extend(line.strip()[1:] for line in reference_bytes.splitlines() if line[:1] in {b"+", b"-"} and not line.startswith((b"+++", b"---", b"@@")) and len(line.strip()) >= 16)
    context_pack = prepare_task_pack(cell_dir.parents[1], task.id, source, task.source_repository, task.source_sha, task.allowed_paths, source_root / "omp-config", forbidden_tokens)
    instruction = task_prompt(task, composition, assets, context_pack=context_pack)
    instruction_path = task_dir / "instruction.md"
    instruction_path.parent.mkdir(parents=True, exist_ok=True)
    instruction_path.write_text(instruction, encoding="utf-8")
    root = cell_dir.parents[1]
    context_dir = root / "context"
    if composition == "controlled_enriched":
        context_manifest_digest = context_pack.manifest_digest
        context_pack_digest = context_pack.pack_digest
    else:
        empty_manifest = {"schema_version": "harness_census.context_manifest.v1", "includes": [], "holdouts": []}
        context_manifest_digest = digest(empty_manifest)
        context_pack_digest = bytes_digest(b"")
        target_manifest = context_dir / "manifests" / f"{context_manifest_digest}.json"
        target_pack = context_dir / "packs" / f"{context_pack_digest}.md"
        target_manifest.parent.mkdir(parents=True, exist_ok=True)
        target_pack.parent.mkdir(parents=True, exist_ok=True)
        if target_manifest.exists() and json.loads(target_manifest.read_text(encoding="utf-8")) != empty_manifest:
            fail(f"immutable context manifest changed: {target_manifest}")
        if not target_manifest.exists():
            write_json(target_manifest, empty_manifest)
        if target_pack.exists() and target_pack.read_bytes() != b"":
            fail(f"immutable context pack changed: {target_pack}")
        if not target_pack.exists():
            target_pack.write_bytes(b"")
    package_name = "prime-package" if harness == "prime" else "runtime-package"
    shutil.copytree(package["path"], env / package_name, symlinks=True, copy_function=lambda source, destination: Path(destination).hardlink_to(source))
    if harness == "prime":
        shutil.copytree(package["node_toolchain_path"], env / "runtime-package", symlinks=True, copy_function=lambda source, destination: Path(destination).hardlink_to(source))
    docker_text = dockerfile(harness, package_name, task.id)
    (env / "Dockerfile").write_text(docker_text, encoding="utf-8")
    task_toml, network_mode = staged_task_toml(task, composition)
    (task_dir / "task.toml").write_text(task_toml, encoding="utf-8")
    gateway = write_gateway_assets(task_dir, allow_user_namespaces=harness == "prime")
    tests = task_dir / "tests"
    tests.mkdir(parents=True, exist_ok=True)
    source_manifest = {name: bytes_digest(value) for name, value in tree_files(source, exclude_git=False).items()}
    (tests / "verify.py").write_text(verifier_source(task.task_dir / "grader.py", source_manifest, task.allowed_paths), encoding="utf-8")
    (tests / "verify.py").chmod(0o755)
    (tests / "test.sh").write_text("#!/bin/sh\nset -eu\nlog_dir=${HARNESS_CENSUS_LOG_DIR:-/logs/verifier}\nexport HARNESS_CENSUS_LOG_DIR=\"$log_dir\"\nverifier=${HARNESS_CENSUS_VERIFIER:-/tests/verify.py}\nworkspace=${HARNESS_CENSUS_WORKSPACE:-/workspace}\nmkdir -p \"$log_dir\"\nchmod 0755 \"$log_dir\"\npython3 \"$verifier\" \"$workspace\"\n", encoding="utf-8")
    (tests / "test.sh").chmod(0o755)
    files = tree_files(task_dir, exclude_git=False)
    if any(any(token in name.split("/") for token in (".git", "grader.py", "reference.patch", "mutants")) for name in files if not name.startswith("environment/repo/")):
        fail(f"staged task leaks qualification material: {task.id}")
    source_digest = tree_digest(source, exclude_git=False)
    grader_digest = file_digest(task.task_dir / "grader.py")
    hunk_map_digest = reference_hunk_map_digest(task)
    comparison_task_digest = task_corpus_identity(task, source_digest, grader_digest, file_digest(task.task_dir / "reference.patch"), hunk_map_digest)
    task_digest = task_identity(task, source_digest, file_digest(instruction_path), file_digest(task_dir / "task.toml"), grader_digest, file_digest(task.task_dir / "reference.patch"), hunk_map_digest)
    skill_digest = context_pack.skill_digest if composition == "controlled_enriched" else raw_skill_digest()
    return TaskRecord(task.id, task.source_cluster, task_digest, comparison_task_digest, grader_digest, hunk_map_digest, bytes_digest(docker_text.encode()), gateway["gateway_digest"], gateway["gateway_dockerfile_digest"], gateway["compose_digest"], f"tasks/{task.id}", task.immutable_paths, network_mode, context_manifest_digest, context_pack_digest, skill_digest, file_digest(instruction_path), context_pack.skill_count if composition == "controlled_enriched" else 0)
def preflight_network_enforcement(cell: Cell) -> dict[str, object]:
    """Prove the staged Compose topology blocks direct worker egress."""
    record = cell.task_records[0]
    environment = cell.cell_dir / record.task_dir / "environment"
    compose_path = environment / "docker-compose.yaml"
    project = f"harness-census-preflight-{digest(str(environment))[:12]}"
    compose = ["docker", "compose", "--project-name", project, "--file", str(compose_path)]
    config = subprocess.run([*compose, "config", "--quiet"], text=True, capture_output=True, check=False)
    if config.returncode:
        detail = (config.stderr or config.stdout).strip().splitlines()[-1:]
        fail(f"Compose network preflight is invalid: {' '.join(detail)}")
    probe_source = """
const http = require("node:http");
const apiPath = "/proxy/https/openrouter.ai/api/v1";
const rejectedTargets = {
  raw_dot_host_escape: apiPath + "/../../../169.254.169.254/latest/meta-data",
  encoded_dot_host_escape: apiPath + "/%2e%2e/%2e%2e/%2e%2e/169.254.169.254/latest/meta-data",
  raw_slash: apiPath + "//models",
  encoded_slash: apiPath + "%2fmodels",
  raw_backslash: apiPath + "/" + String.fromCharCode(92) + "models",
  encoded_backslash: apiPath + "/%5cmodels",
  loopback_host_escape: apiPath + "/../../../127.0.0.1:80/",
  rfc1918_host_escape: apiPath + "/../../../192.168.0.1/",
};
function requestStatus(path, method = "GET", headers = {}) {
  return new Promise(resolve => {
    try {
      const request = http.request({ hostname: "mint-gateway", port: 4949, path, method, headers }, response => {
        response.resume();
        response.once("end", () => resolve(response.statusCode || 0));
      });
      request.once("error", () => resolve(0));
      request.setTimeout(3000, () => {
        request.destroy();
        resolve(0);
      });
      request.end();
    } catch {
      resolve(0);
    }
  });
}
(async () => {
  const directBlocked = await fetch("http://1.1.1.1", {
    signal: AbortSignal.timeout(3000),
  }).then(() => false, () => true);
  const gatewayStatus = await fetch("http://mint-gateway:4949/", {
    signal: AbortSignal.timeout(3000),
  }).then(response => response.status, () => 0);
  const targetStatuses = {};
  for (const [name, path] of Object.entries(rejectedTargets)) targetStatuses[name] = await requestStatus(path);
  const methodStatus = await requestStatus(apiPath, "DELETE");
  const wrongPathStatus = await requestStatus("/");
  const upgradeStatus = await requestStatus(apiPath, "GET", { Connection: "Upgrade", Upgrade: "websocket" });
  const allTargetsRejected = Object.values(targetStatuses).every(status => status === 404);
  if (!directBlocked || gatewayStatus !== 404 || !allTargetsRejected || methodStatus !== 405 || wrongPathStatus !== 404 || upgradeStatus !== 400) process.exit(1);
})().catch(() => process.exit(1));
"""
    failure: str | None = None
    try:
        start = subprocess.run([*compose, "up", "--build", "--detach", "--wait", "--wait-timeout", "30", "mint-gateway"], text=True, capture_output=True, check=False)
        if start.returncode:
            failure = " ".join((start.stderr or start.stdout).strip().splitlines()[-1:])
        else:
            probe = subprocess.run(
                [*compose, "run", "--build", "--rm", "--no-deps", "--entrypoint", "node", "main", "-e", probe_source],
                text=True,
                capture_output=True,
                check=False,
            )
            if probe.returncode:
                failure = " ".join((probe.stderr or probe.stdout).strip().splitlines()[-1:])
    finally:
        subprocess.run([*compose, "down", "--volumes", "--remove-orphans", "--rmi", "local"], text=True, capture_output=True, check=False)
    if failure is not None:
        fail(f"Compose network enforcement preflight failed: {failure}")
    return {
        "status": "passed",
        "worker_direct_egress": "blocked",
        "gateway_reachable": True,
        "gateway_service": "mint-gateway",
        "gateway_path_rejection": True,
        "gateway_path_rejection_probes": [
            "raw_dot_host_escape",
            "encoded_dot_host_escape",
            "raw_slash",
            "encoded_slash",
            "raw_backslash",
            "encoded_backslash",
            "loopback_host_escape",
            "rfc1918_host_escape",
            "wrong_path",
        ],
        "gateway_method_rejection": True,
        "gateway_upgrade_rejection": True,
        "gateway_port": 4949,
    }


def preflight_worker_images(root: Path, cells: tuple[Cell, ...]) -> dict[str, object]:
    """Build every harness/task image and run its hidden reference grader inside it."""
    if not shutil.which("docker"):
        fail("worker image preflight requires docker before provider calls")
    tasks = load_tasks()
    representatives = {
        harness: next(cell for cell in cells if cell.harness == harness and cell.composition == "native_default")
        for harness in HARNESSES
    }
    network_report = preflight_network_enforcement(representatives["prime"])
    results: list[dict[str, object]] = []
    command = (
        "set -eu; test ! -e /workspace/grader.py && test ! -e /workspace/reference.patch; "
        "mkdir -p /tmp/home /tmp/go-cache /tmp/cargo-target /tmp/bun-cache; "
        "rm -rf /tmp/reference-repo /tmp/grader-output; cp -a /workspace /tmp/reference-repo; "
        "patch --batch --forward -p1 -d /tmp/reference-repo < /qualification/reference.patch; "
        "set +e; python3 /qualification/grader.py /tmp/reference-repo > /tmp/grader-output; grader_rc=$?; set -e; "
        "python3 - /tmp/grader-output /preflight/reward.json \"$grader_rc\" <<'PY'\n"
        "import json, pathlib, sys\n"
        "lines = [line for line in pathlib.Path(sys.argv[1]).read_text(encoding='utf-8').splitlines() if line.strip()]\n"
        "report = json.loads(lines[-1]) if lines else {}\n"
        "reward = 1.0 if int(sys.argv[3]) == 0 and report.get('passed') is True else 0.0\n"
        "pathlib.Path(sys.argv[2]).write_text(json.dumps({'reward': reward}) + '\\n', encoding='utf-8')\n"
        "print(json.dumps({'reward': reward, 'report': report}, sort_keys=True))\n"
        "raise SystemExit(0 if reward == 1.0 else 1)\n"
        "PY"
    )
    prime_sandbox_args = (
        "bwrap", "--die-with-parent", "--unshare-user", "--uid", "0", "--gid", "0", "--unshare-net",
        "--proc", "/proc", "--dev", "/dev", "--ro-bind", "/usr", "/usr", "--ro-bind", "/bin", "/bin",
        "--ro-bind", "/lib", "/lib", "--ro-bind", "/lib64", "/lib64", "/usr/bin/true",
    )
    with tempfile.TemporaryDirectory(prefix="harness-census-preflight-") as temporary:
        workspace = Path(temporary)
        for harness, representative in sorted(representatives.items()):
            for task_id, task in tasks.items():
                task_root = representative.cell_dir / next(record.task_dir for record in representative.task_records if record.task_id == task_id)
                environment = task_root / "environment"
                context = workspace / f"{harness}-{task_id}"
                shutil.copytree(environment / "repo", context / "repo", symlinks=True)
                package_name = "prime-package" if harness == "prime" else "runtime-package"
                shutil.copytree(environment / package_name, context / package_name, symlinks=True)
                if harness == "prime":
                    shutil.copytree(environment / "runtime-package", context / "runtime-package", symlinks=True)
                (context / "Dockerfile").write_text(dockerfile(harness, package_name, task_id), encoding="utf-8")
                tag = f"harness-census-preflight-{CAMPAIGN_ID}-{harness}-{task_id}"
                build = subprocess.run(
                    ["docker", "build", "--pull=false", "--tag", tag, str(context)],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if build.returncode:
                    detail = (build.stderr or build.stdout).strip().splitlines()[-1:]
                    fail(f"{harness}/{task_id} worker image build failed: {' '.join(detail)}")
                output = workspace / f"{harness}-{task_id}-result"
                output.mkdir()
                mounts = [
                    f"{task.task_dir / 'reference.patch'}:/qualification/reference.patch:ro",
                    f"{task.task_dir / 'grader.py'}:/qualification/grader.py:ro",
                    f"{output}:/preflight:rw",
                ]
                try:
                    if harness == "prime":
                        sandbox = subprocess.run(
                            [
                                "docker", "run", "--rm", "--network", "none", "--read-only",
                                "--security-opt", "seccomp=unconfined",
                                "--tmpfs", "/tmp:rw,exec,nosuid,nodev", tag, *prime_sandbox_args,
                            ],
                            text=True,
                            capture_output=True,
                            check=False,
                        )
                        if sandbox.returncode:
                            detail = (sandbox.stderr or sandbox.stdout).strip().splitlines()[-1:]
                            fail(f"{harness}/{task_id} inner sandbox preflight failed: {' '.join(detail)}")
                    run = subprocess.run(
                        [
                            "docker", "run", "--rm", "--network", "none", "--read-only",
                            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                            "--tmpfs", "/tmp:rw,exec,nosuid,nodev",
                            *sum((["--volume", mount] for mount in mounts), []),
                            "--env", "HOME=/tmp/home", "--env", "GOCACHE=/tmp/go-cache",
                            "--env", "CARGO_TARGET_DIR=/tmp/cargo-target", "--env", "BUN_INSTALL_CACHE_DIR=/tmp/bun-cache",
                            "--entrypoint", "/bin/sh", tag, "-c", command,
                        ],
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                finally:
                    subprocess.run(["docker", "image", "rm", "--force", tag], text=True, capture_output=True, check=False)
                reward_path = output / "reward.json"
                if run.returncode or not reward_path.is_file():
                    detail = (run.stderr or run.stdout).strip().splitlines()[-1:]
                    fail(f"{harness}/{task_id} in-image grader failed: {' '.join(detail)}")
                reward = harbor_reward_value(json.loads(reward_path.read_text(encoding="utf-8")))
                if reward != 1.0:
                    fail(f"{harness}/{task_id} preflight reward is not 1.0: {reward!r}")
                results.append({"harness": harness, "task_id": task_id, "reward": reward, "sandbox": "bwrap-user-net" if harness == "prime" else "container"})
    report = {
        "status": "passed",
        "network": "none",
        "filesystem": "read-only-root-tmpfs-tmp",
        "toolchains": {"go": GO_VERSION, "rustc": RUST_VERSION, "cargo": CARGO_VERSION, "bun": BUN_VERSION, "pnpm": "10.22.0"},
        "prime_inner_sandbox": "bwrap-user-net",
        "checks": len(results),
        "results": results,
        "network_enforcement": network_report,
    }
    if len(results) != 9:
        fail(f"worker preflight checked {len(results)} images, expected 9")
    write_json(root / "worker-preflight.json", report)
    return report


def probe_harbor_task_validity(cells: tuple[Cell, ...]) -> dict[str, object]:
    task_paths = sorted({cell.cell_dir / record.task_dir for cell in cells for record in cell.task_records}, key=str)
    task_ids = {path.name for path in task_paths}
    controlled = [record for cell in cells if cell.cell_kind == "controlled" for record in cell.task_records]
    if not controlled or {record.network_mode for record in controlled} != {CONTROLLED_NETWORK_MODE}:
        fail("controlled staged tasks do not use configured task network mode")
    if task_ids != set(load_tasks()):
        fail(f"staged Harbor task set is invalid: {sorted(task_ids)}")
    check = """from pathlib import Path
import sys
from harbor.models.task.task import Task
paths = [Path(value) for value in sys.argv[1:]]
invalid = [str(path) for path in paths if not Task.is_valid_dir(path)]
if invalid:
    print("invalid staged tasks: " + ", ".join(invalid), file=sys.stderr)
    raise SystemExit(1)
print(f"Harbor 0.13.1 valid staged tasks={len(paths)}")
"""
    try:
        from harness_census_exchange import safe_runtime_environment

        result = subprocess.run(["uvx", "--from", f"harbor=={HARBOR_VERSION}", "python", "-c", check, *map(str, task_paths)], env=safe_runtime_environment(), text=True, capture_output=True, check=False)
    except OSError as error:
        fail(f"Harbor {HARBOR_VERSION} staged task validity probe could not start: {error}")
    if result.returncode:
        detail = (result.stderr or result.stdout).strip().splitlines()[-1:]
        fail(f"Harbor {HARBOR_VERSION} staged task validity failed: {' '.join(detail)}")
    return {"version": HARBOR_VERSION, "task_count": len(task_paths), "task_ids": sorted(task_ids), "all_valid": True, "controlled_task_count": len(controlled), "transport_network_mode": CONTROLLED_TRANSPORT_NETWORK_MODE, "task_network_enforcement": CONTROLLED_TASK_NETWORK_ENFORCEMENT}


def copy_adapters(campaign_root: Path, adapter_root: Path) -> str:
    source = adapter_root / "harbor_agents" if adapter_root.name != "harbor_agents" and (adapter_root / "harbor_agents").is_dir() else adapter_root
    if not source.is_dir():
        fail(f"pinned harbor_agents package is missing: {source}")
    destination = campaign_root / "cells" / "harbor_agents"
    shutil.copytree(source, destination)
    required = {"__init__.py", "prime_agent.py", "prime_kernel_wrapper.sh", "omp_agent.py", "pi_agent.py"}
    if not required.issubset(path.name for path in destination.iterdir()):
        fail("pinned harbor_agents package is incomplete")
    return tree_digest(destination, exclude_git=False)


def probe_controlled_argv_surfaces(adapter_root: Path) -> dict[str, object]:
    source = adapter_root / "harbor_agents" if adapter_root.name != "harbor_agents" and (adapter_root / "harbor_agents").is_dir() else adapter_root
    common_path = source / "adapter_common.py"
    if not common_path.is_file():
        fail(f"adapter command contract is missing: {common_path}")
    package_parent = str(source.parent)
    sys.path.insert(0, package_parent)
    try:
        module = importlib.import_module("harbor_agents.adapter_common")
    except (ImportError, OSError) as error:
        fail(f"adapter command contract cannot load: {common_path}: {error}")
    finally:
        sys.path.remove(package_parent)
    build_argv = getattr(module, "build_argv", None)
    if not callable(build_argv):
        fail("adapter command contract does not expose build_argv")
    wrapper_path = source / "prime_kernel_wrapper.sh"
    wrapper = wrapper_path.read_text(encoding="utf-8") if wrapper_path.is_file() else ""
    if "env -i" not in wrapper or "--unshare-net" not in wrapper:
        fail("Prime IPython wrapper does not clear ambient credentials and deny network")
    prime_guard = {"kind": "bwrap_unshare_net_clean_env", "digest": file_digest(wrapper_path)}
    expected_tools = {"prime": "ipython", "omp": "read,edit,write", "pi": "read,edit,write"}
    required_flags = {"prime": ("--no-context-files", "--no-extensions", "--no-prompt-templates", "--no-skills", "--no-themes"), "omp": ("--no-extensions", "--no-rules", "--no-skills"), "pi": ("--no-context-files", "--no-extensions", "--no-prompt-templates", "--no-skills", "--no-themes")}
    enabled_context_flags = {"--context", "--context-file", "--extension", "--extensions", "--mcp", "--rule", "--rules", "--skill", "--skills", "--theme", "--themes", "--prompt-template", "--prompt-templates"}
    records: list[dict[str, object]] = []
    for name in HARNESSES:
        command = list(build_argv(name, composition="controlled_raw", provider="openrouter", model="probe", thinking=CONTROLLED_EFFORT, instruction="controlled-probe", profile="harness-census-probe"))
        if any(marker in token.lower() for token in command for marker in ("shell", "process", "browser", "mcp")) or any(token in enabled_context_flags for token in command) or any(flag not in command for flag in required_flags[name]):
            fail(f"controlled {name} argv exposes an undeclared surface: {command}")
        try:
            tools = command[command.index("--tools") + 1]
        except (ValueError, IndexError):
            fail(f"controlled {name} argv has no declared tool surface: {command}")
        if tools != expected_tools[name]:
            fail(f"controlled {name} argv tool surface is {tools!r}, expected {expected_tools[name]!r}")
        record: dict[str, object] = {"adapter": name, "tool_surface": tools, "argv_digest": digest(command), "context_flags": list(required_flags[name])}
        if name == "prime":
            record["tool_network_guard"] = prime_guard
        records.append(record)
    return {"status": "passed", "task_network": "denied_by_tool_and_sandbox", "adapters": records}




def immutable_stage_cells(cells: tuple[Cell, ...]) -> dict[str, object]:
    tasks = load_tasks()
    return {
        cell.cell_id: {
            "summary": cell_summary(cell),
            "tasks": [
                {
                    "task_id": record.task_id,
                    "task_digest": record.task_digest,
                    "comparison_task_digest": record.comparison_task_digest,
                    "reference_hunk_map_digest": record.reference_hunk_map_digest,
                    "source_cluster": record.source_cluster,
                    "dockerfile_digest": record.dockerfile_digest,
                    "gateway_digest": record.gateway_digest,
                    "gateway_dockerfile_digest": record.gateway_dockerfile_digest,
                    "compose_digest": record.compose_digest,
                    "grader_digest": record.grader_digest,
                    "context_manifest_digest": record.context_manifest_digest,
                    "context_pack_digest": record.context_pack_digest,
                    "context_digest": record.context_digest,
                    "skill_digest": record.skill_digest,
                    "skill_count": record.skill_count,
                }
                for record in cell.task_records
            ],
        }
        for cell in cells
    }

def build_cells(root: Path, assets: Mapping[str, str], composition_digests: Mapping[str, str], source_root: Path, adapter_root: Path, prime_package: dict[str, str] | None) -> tuple[Cell, ...]:
    validate_gateway_contract()
    tasks = load_tasks()
    adapter_digest = copy_adapters(root, adapter_root)
    cells: list[Cell] = []
    packages = {harness: harness_package_info(harness, prime_package) for harness in HARNESSES}
    for row in campaign_matrix():
        harness, composition = str(row["harness"]), str(row["composition"])
        spec, package = HARNESSES[harness], packages[harness]
        cell_id, cell_dir = str(row["cell_id"]), root / "cells" / str(row["cell_id"])
        cell_dir.mkdir(parents=True, exist_ok=True)
        records = tuple(stage_task(cell_dir, tasks[task_id], harness, composition, assets, source_root, package) for task_id in tasks)
        task_digest = digest([record.task_digest for record in records])
        task_set = [(record.task_id, record.comparison_task_digest) for record in records]
        task_set_digest = canonical_task_set_digest(task_set)
        task_set_size = len(task_set)
        cell_run_id = f"{CAMPAIGN_ID}--{cell_id}"
        retry_policy_digest = digest({"product_retry": 0, "transport_retry": 0})
        controlled = composition != "native_default"
        network_mode = CONTROLLED_NETWORK_MODE if controlled else NATIVE_NETWORK_MODE
        network_enforcement = CONTROLLED_NETWORK_ENFORCEMENT if controlled else NATIVE_NETWORK_ENFORCEMENT
        transport_mode = CONTROLLED_TRANSPORT_NETWORK_MODE if controlled else NATIVE_TRANSPORT_NETWORK_MODE
        task_enforcement = CONTROLLED_TASK_NETWORK_ENFORCEMENT if controlled else NATIVE_TASK_NETWORK_ENFORCEMENT
        allowed_hosts = AGENT_ALLOWED_HOSTS
        model, effort = row["model_requested"], row["effort_requested"]
        kwargs: Mapping[str, object] = {"composition": composition, "thinking": CONTROLLED_EFFORT, "mint_base_url": MINT_INTERNAL_BASE_URL} if controlled else {"composition": "native_default", "mint_base_url": MINT_INTERNAL_BASE_URL}
        agent_kwargs_base_digest = digest({key: value for key, value in kwargs.items() if key not in {"composition", "thinking", "reasoning_effort"}})
        config: dict[str, object] = {"agent": harness, "agent_import_path": spec.adapter, "job_timeout_ms": 900000, "agent_kwargs": dict(kwargs)}
        if controlled:
            config["model"] = CONTROLLED_MODEL
        spec_json = {"schema_version": "crucible.eval_spec.v1", "id": cell_id, "task": CAMPAIGN_ID, "inputs": "Three history-free pinned repository repair tasks with deterministic graders.", "outputs": "Harbor verifier reward per task.", "graders": {"graders": [{"id": "harness_census_deterministic", "kind": "deterministic"}]}, "aggregation": "proportion", "uncertainty": {"method": "wilson", "confidence": 0.95}, "decision": "Native defaults remain separate from controlled comparisons.", "runner": {"kind": "harbor_task", "corpus": {"source": "harbor_tasks", "config": config, "tasks": [{"task_id": record.task_id, "task_dir": record.task_dir} for record in records]}}}
        spec_path = cell_dir / "eval.json"
        write_json(spec_path, spec_json)
        gateway_digests = tuple(sorted({record.gateway_digest for record in records}))
        gateway_dockerfile_digests = tuple(sorted({record.gateway_dockerfile_digest for record in records}))
        compose_digests = tuple(sorted({record.compose_digest for record in records}))
        composition_identity = {"mint_base_url": MINT_INTERNAL_BASE_URL, "gateway_digests": list(gateway_digests), "gateway_dockerfile_digests": list(gateway_dockerfile_digests), "compose_digests": list(compose_digests)}
        if composition == "native_default":
            composition_digest = digest({"composition": composition, **composition_identity})
        elif composition == "controlled_raw":
            composition_digest = digest({"composition": composition, "restriction_digest": bytes_digest((assets["controlled_raw"].strip() + "\n").encode("utf-8")), "skill_digest": records[0].skill_digest, "skill_count": 0, **composition_identity})
        else:
            composition_digest = digest({"composition": composition, "context_manifest_digests": [record.context_manifest_digest for record in records], "context_pack_digests": [record.context_pack_digest for record in records], "skill_digest": records[0].skill_digest, "skill_count": records[0].skill_count, **composition_identity})
        docker_digests = tuple(sorted({record.dockerfile_digest for record in records}))
        package_digest = package["digest"]
        prime_digest = package["prime_digest"] if harness == "prime" else None
        row_id = row_identity(CONTROLLED_MODEL, CONTROLLED_EFFORT, harness, composition) if controlled else None
        cohort_id = cohort_identity(CONTROLLED_MODEL, CONTROLLED_EFFORT, CONTROLLED_MODEL, CONTROLLED_EFFORT) if controlled else None
        baseline_id = None
        profile = digest({"harness": harness, "version": spec.version, "adapter_digest": adapter_digest, "kwargs": kwargs, "task_digest": task_digest, "composition_digest": composition_digest, "package_digest": package_digest, "prime_package_digest": prime_digest, "dockerfile_digests": list(docker_digests), **composition_identity, "transport_network_mode": transport_mode, "network_enforcement": network_enforcement, "task_network_enforcement": task_enforcement})
        cells.append(
            Cell(
                cell_id=cell_id,
                cell_run_id=cell_run_id,
                task_set_digest=task_set_digest,
                task_set_size=task_set_size,
                retry_policy_digest=retry_policy_digest,
                agent_kwargs_base_digest=agent_kwargs_base_digest,
                cell_dir=cell_dir,
                spec_path=spec_path,
                cell_kind="controlled" if controlled else "native_default",
                harness=harness,
                harness_version=spec.version,
                composition=composition,
                model_requested=model if isinstance(model, str) else None,
                effort_requested=effort if isinstance(effort, str) else None,
                provider_route_resolved=model if isinstance(model, str) else None,
                provider_effort_resolved=effort if isinstance(effort, str) else None,
                default_resolution_source=None,
                effort_source="requested" if controlled else None,
                row_id=row_id,
                cohort_id=cohort_id,
                baseline_id=baseline_id,
                profile_digest=profile,
                agent_kwargs=kwargs,
                agent_allowed_hosts=tuple(allowed_hosts),
                network_mode=network_mode,
                transport_network_mode=transport_mode,
                network_enforcement=network_enforcement,
                task_network_enforcement=task_enforcement,
                task_digest=task_digest,
                composition_digest=composition_digest,
                adapter_digest=adapter_digest,
                package_digest=package_digest,
                dockerfile_digests=docker_digests,
                gateway_digests=gateway_digests,
                gateway_dockerfile_digests=gateway_dockerfile_digests,
                compose_digests=compose_digests,
                task_records=records,
            )
        )
    if len(cells) != 9 or sum(len(cell.task_records) for cell in cells) != 27:
        fail("driver matrix is not exactly 9 cells and 27 trials")
    controlled = [cell for cell in cells if cell.cell_kind == "controlled"]
    if len({cell.row_id for cell in controlled}) != 6 or len({cell.cohort_id for cell in controlled}) != 1:
        fail("controlled rows are not unique and pairable")
    for cell in cells:
        config = json.loads(cell.spec_path.read_text(encoding="utf-8"))["runner"]["corpus"]["config"]
        spec = HARNESSES[cell.harness]
        if cell.cell_kind == "native_default":
            expected = {"agent": cell.harness, "agent_import_path": spec.adapter, "job_timeout_ms": 900000, "agent_kwargs": {"composition": "native_default", "mint_base_url": MINT_INTERNAL_BASE_URL}}
            valid = config == expected and cell.network_mode == NATIVE_NETWORK_MODE and cell.transport_network_mode == NATIVE_TRANSPORT_NETWORK_MODE and cell.network_enforcement == NATIVE_NETWORK_ENFORCEMENT and cell.task_network_enforcement == NATIVE_TASK_NETWORK_ENFORCEMENT and cell.agent_allowed_hosts == AGENT_ALLOWED_HOSTS and cell.model_requested is None and cell.effort_requested is None and cell.provider_route_resolved is None and cell.provider_effort_resolved is None and cell.default_resolution_source is None
        else:
            expected = {"agent": cell.harness, "agent_import_path": spec.adapter, "job_timeout_ms": 900000, "model": CONTROLLED_MODEL, "agent_kwargs": {"composition": cell.composition, "thinking": CONTROLLED_EFFORT, "mint_base_url": MINT_INTERNAL_BASE_URL}}
            valid = config == expected and cell.network_mode == CONTROLLED_NETWORK_MODE and cell.transport_network_mode == CONTROLLED_TRANSPORT_NETWORK_MODE and cell.network_enforcement == CONTROLLED_NETWORK_ENFORCEMENT and cell.task_network_enforcement == CONTROLLED_TASK_NETWORK_ENFORCEMENT and cell.agent_allowed_hosts == AGENT_ALLOWED_HOSTS and cell.model_requested == CONTROLLED_MODEL and cell.effort_requested == CONTROLLED_EFFORT and cell.provider_route_resolved == CONTROLLED_MODEL and cell.provider_effort_resolved == CONTROLLED_EFFORT
        if not valid:
            fail(f"staged config or metadata shape is invalid: {cell.cell_id}")
    return tuple(cells)


def write_harbor_wrapper(root: Path) -> Path:
    wrapper = confined_path(root, "bin", "harbor")
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text(f"#!/bin/sh\nset -eu\nexec uvx --from harbor=={HARBOR_VERSION} harbor \"$@\"\n", encoding="utf-8")
    wrapper.chmod(0o755)
    return wrapper


def read_verifier_result(log_dir: Path) -> tuple[float, dict[str, object]]:
    reward_path, report_path = log_dir / "reward.json", log_dir / "grader-report.json"
    if not reward_path.is_file() or not report_path.is_file():
        fail(f"staged verifier evidence is incomplete: {log_dir}")
    reward = harbor_reward_value(json.loads(reward_path.read_text(encoding="utf-8")))
    if reward is None:
        fail("Harbor reward.json must contain one canonical bounded reward map")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        fail(f"grader report is not an object: {report!r}")
    if report.get("task_points") != reward or not isinstance(report.get("hard_pass"), bool) or report.get("passed") != report.get("hard_pass"):
        fail(f"staged verifier score identity is invalid: {report!r}")
    return reward, report


def probe_verifier(root: Path, cell: Cell) -> dict[str, object]:
    task = cell.cell_dir / cell.task_records[0].task_dir
    log_dir = root / "probes" / cell.cell_id
    environment = {**os.environ, "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}", "HARNESS_CENSUS_LOG_DIR": str(log_dir), "HARNESS_CENSUS_VERIFIER": str(task / "tests" / "verify.py"), "HARNESS_CENSUS_WORKSPACE": str(task / "environment" / "repo")}
    result = subprocess.run([str(task / "tests" / "test.sh")], env=environment, text=True, capture_output=True, check=False)
    reward, report = read_verifier_result(log_dir)
    if report.get("status") != "quality_failure" or reward != 0.0:
        fail(f"unchanged staged task did not produce quality failure: {report}")
    return {"cell_id": cell.cell_id, "return_code": result.returncode, "status": report["status"], "reward": reward, "grader_report": report.get("grader_report")}


def run_scope_probes(root: Path, cell: Cell) -> dict[str, object]:
    record, task, source = cell.task_records[0], cell.cell_dir / cell.task_records[0].task_dir, cell.cell_dir / cell.task_records[0].task_dir / "environment" / "repo"
    with tempfile.TemporaryDirectory(prefix="harness-census-scope-") as temporary:
        scratch = Path(temporary)
        unrelated = scratch / "unrelated"
        shutil.copytree(source, unrelated, symlinks=True)
        immutable_file = unrelated / record.immutable_paths[0]
        immutable_file.write_bytes(immutable_file.read_bytes() + b"\nscope probe\n")
        bad_log = scratch / "bad-log"
        bad = subprocess.run([sys.executable, str(task / "tests" / "verify.py"), str(unrelated)], env={**os.environ, "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}", "HARNESS_CENSUS_LOG_DIR": str(bad_log)}, text=True, capture_output=True, check=False)
        _, bad_report = read_verifier_result(bad_log)
        if bad.returncode == 0 or bad_report.get("grader_report", {}).get("failed_check") != "scope":
            fail(f"unrelated scope probe did not fail scope: {bad_report}")
        allowed = scratch / "allowed"
        shutil.copytree(source, allowed, symlinks=True)
        patch = load_tasks()[record.task_id].task_dir / "reference.patch"
        checked = subprocess.run(["git", "-C", str(allowed), "apply", "--check", str(patch)], text=True, capture_output=True, check=False)
        if checked.returncode:
            fail(f"reference scope probe cannot apply: {checked.stderr.strip()}")
        applied = subprocess.run(["git", "-C", str(allowed), "apply", str(patch)], text=True, capture_output=True, check=False)
        if applied.returncode:
            fail(f"reference scope probe failed: {applied.stderr.strip()}")
        good_log = scratch / "good-log"
        good = subprocess.run([sys.executable, str(task / "tests" / "verify.py"), str(allowed)], env={**os.environ, "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}", "HARNESS_CENSUS_LOG_DIR": str(good_log)}, text=True, capture_output=True, check=False)
        good_reward, good_report = read_verifier_result(good_log)
        if good.returncode or good_report.get("status") != "success" or good_reward != 1.0:
            fail(f"reference scope probe did not pass quality and scope: {good_report}")
    return {"unrelated_mutation": {"passed": True, "status": bad_report["status"], "failed_check": bad_report["grader_report"]["failed_check"]}, "allowed_reference": {"passed": True, "status": good_report["status"], "reward": good_reward}}




def staged_bytes_digest(root: Path) -> str:
    files: dict[str, bytes] = {}
    for name, value in campaign_tree_files(root, skip=("cells/*/tasks/*/environment/repo/*", "cells/*/request.json", "cells/*/result.json", "cells/*/results/*", "cells/*/runs/*")).items():
        parts = name.split("/")
        if parts[0] in {"context", "packages"} or name == "bin/harbor":
            files[name] = value
        elif parts[0] == "cells" and len(parts) > 1:
            relative = "/".join(parts[2:])
            if parts[1] == "harbor_agents" or (relative not in {"request.json", "result.json"} and not relative.startswith("results/")):
                if not (len(parts) >= 6 and parts[2] == "tasks" and parts[4:6] == ["environment", "repo"]):
                    files[name] = value
    return digest([(name, bytes_digest(value)) for name, value in sorted(files.items())])


def _receipt_rows(root: Path, cell: Cell) -> list[tuple[dict[str, object], int | None]]:
    db = confined_path(root, "runs", "campaign.sqlite")
    if not db.is_file():
        return []
    with sqlite3.connect(db) as connection:
        tables = {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"harness_census_receipts", "runner_exchange_records"}.issubset(tables):
            return []
        trusted_sql = ", r.trusted" if "run_records" in tables else ", NULL"
        rows = connection.execute(
            "SELECT c.receipt_json, c.crucible_run_id" + trusted_sql + " FROM harness_census_receipts c "
            "JOIN runner_exchange_records e ON e.record_id = c.exchange_record_id "
            + ("LEFT JOIN run_records r ON r.run_id = c.cell_run_id " if "run_records" in tables else "")
            + "WHERE c.campaign_id = ?",
            (CAMPAIGN_ID,),
        ).fetchall()
    parsed: list[tuple[dict[str, object], int | None]] = []
    for raw, run_id, trusted in rows:
        try:
            receipt = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            fail(f"resume receipt is not valid JSON: {cell.cell_id}")
        if not isinstance(receipt, dict):
            fail(f"resume receipt is not an object: {cell.cell_id}")
        identity = receipt.get("cell_id") or receipt.get("cell_run_id") or str(run_id)
        if identity == cell.cell_id or identity == cell.cell_run_id or str(run_id).startswith(f"{CAMPAIGN_ID}--{cell.cell_id}--"):
            parsed.append((receipt, trusted))
    return parsed


def _receipt_identity(receipt: dict[str, object], cell: Cell, stage_digest: str, task_id: str) -> bool:
    def ref(value: object, expected: str) -> bool:
        return value in {expected, f"sha256:{expected}"}

    expected = {
        "campaign_id": CAMPAIGN_ID,
        "cell_id": cell.cell_id,
        "cell_run_id": cell.cell_run_id,
        "task_set_size": cell.task_set_size,
        "task_name": task_id,
        "task_id": task_id,
        "trial_id": f"{cell.cell_id}--{task_id}",
        "crucible_run_id": f"{CAMPAIGN_ID}--{cell.cell_id}--{task_id}",
    }
    for key, value in expected.items():
        if key in receipt and receipt[key] != value:
            return False
    return (
        receipt.get("schema_version") == "harness_census.trial_receipt.v1"
        and ref(receipt.get("stage_manifest_digest"), stage_digest)
        and ref(receipt.get("task_set_digest"), cell.task_set_digest)
        and ref(receipt.get("retry_policy_digest"), cell.retry_policy_digest)
        and ref(receipt.get("agent_kwargs_base_digest"), cell.agent_kwargs_base_digest)
        and receipt.get("trial_status") in {"success", "quality_failure", "reliability_failure"}
    )


def _parse_content_ref(value: object, label: str) -> tuple[str, str]:
    if not isinstance(value, str):
        fail(f"resume {label} is missing")
    digest_part, separator, relative = value.partition("@")
    if not separator or not digest_part.startswith("sha256:") or not _valid_digest(digest_part.removeprefix("sha256:")):
        fail(f"resume {label} is not a canonical content reference: {value}")
    parts = relative.split("/")
    if any(not part or part in {".", ".."} or "\\" in part or ":" in part for part in parts):
        fail(f"resume {label} has an unsafe content path: {value}")
    return digest_part.removeprefix("sha256:"), relative


def _verify_content_ref(root: Path, value: object, label: str) -> Path:
    expected, relative = _parse_content_ref(value, label)
    path = confined_path(root, *relative.split("/"))
    try:
        actual = bytes_digest(path.read_bytes())
    except OSError as error:
        fail(f"resume {label} content is unreadable: {relative}: {error}")
    if actual != expected:
        fail(f"resume {label} content digest mismatch: {relative}")
    return path


def _receipt_attestation(root: Path, cell: Cell, record: TaskRecord, receipt: dict[str, object]) -> tuple[dict[str, object], str]:
    task_exchange = confined_path(root, "exchange", cell.cell_id, record.task_id)
    result_path = _verify_content_ref(root, receipt.get("runner_exchange_result_ref") or receipt.get("result_ref"), "runner-exchange result")
    if result_path != task_exchange / "result.json":
        fail(f"resume runner-exchange result reference mismatch: {cell.cell_id} {record.task_id}")
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        fail(f"resume runner-exchange result is invalid: {cell.cell_id} {record.task_id}: {error}")
    evidence = result.get("evidence") if isinstance(result, dict) else None
    matches = [item for item in evidence if isinstance(item, dict) and item.get("kind") == "attestation"] if isinstance(evidence, list) else []
    if len(matches) != 1:
        fail(f"resume runner-exchange attestation evidence must contain exactly one item: {cell.cell_id} {record.task_id}")
    item = matches[0]
    relative = item.get("path")
    expected_prefix = f"cells/{cell.cell_id}/results/harbor-jobs/{record.task_id}/"
    if not isinstance(relative, str) or not relative.startswith(expected_prefix):
        fail(f"resume attestation path is outside the current task result directory: {cell.cell_id} {record.task_id}")
    raw_digest = item.get("sha256")
    if isinstance(raw_digest, str) and raw_digest.startswith("sha256:"):
        raw_digest = raw_digest.removeprefix("sha256:")
    if not _valid_digest(raw_digest):
        fail(f"resume attestation evidence digest is invalid: {cell.cell_id} {record.task_id}")
    attestation_path = _verify_content_ref(root, f"sha256:{raw_digest}@{relative}", "attestation evidence")
    attestation_ref = f"sha256:{raw_digest}@{relative}"
    evidence_refs = receipt.get("evidence_refs")
    if not isinstance(evidence_refs, list) or attestation_ref not in evidence_refs:
        fail(f"resume attestation evidence reference is not bound to the receipt: {cell.cell_id} {record.task_id}")
    try:
        attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        fail(f"resume attestation is invalid: {cell.cell_id} {record.task_id}: {error}")
    if not isinstance(attestation, dict) or attestation.get("schema_version") != "crucible.adapter_attestation.v1" or attestation.get("adapter") != cell.harness or attestation.get("composition") != cell.composition or attestation.get("version") != cell.harness_version:
        fail(f"resume attestation adapter identity mismatch: {cell.cell_id} {record.task_id}")
    for key, expected in {"harness": cell.harness, "composition": cell.composition, "harness_version": cell.harness_version}.items():
        if receipt.get(key) != expected:
            fail(f"resume receipt {key} is not bound to the attestation: {cell.cell_id} {record.task_id}")
    observed = attestation.get("observed_identities")
    if attestation.get("status") == "passed":
        if not isinstance(observed, list) or len(observed) != 1 or not isinstance(observed[0], str) or not observed[0].strip():
            fail(f"resume attestation observed model identity is invalid: {cell.cell_id} {record.task_id}")
        effort, effort_source = attestation.get("effort"), attestation.get("effort_source")
        if not isinstance(effort, str) or not effort.strip() or not isinstance(effort_source, str) or not effort_source.strip():
            fail(f"resume attestation effort identity is invalid: {cell.cell_id} {record.task_id}")
        required_bindings = {"provider_route_resolved": observed[0], "provider_effort_resolved": effort, "effort_source": effort_source}
        optional_bindings = {"response_model_attestation": observed[0], "response_effort_attestation": effort}
        for key, expected in required_bindings.items():
            if receipt.get(key) != expected:
                fail(f"resume attestation {key} is not bound to the receipt: {cell.cell_id} {record.task_id}")
        for key, expected in optional_bindings.items():
            if receipt.get(key) is not None and receipt[key] != expected:
                fail(f"resume attestation {key} is not bound to the receipt: {cell.cell_id} {record.task_id}")
    return attestation, relative


def _verified_task_receipt(root: Path, cell: Cell, record: TaskRecord, stage_digest: str, receipt: dict[str, object], trusted: int | None) -> tuple[bool, dict[str, str] | None]:
    if not _receipt_identity(receipt, cell, stage_digest, record.task_id):
        fail(f"resume receipt identity mismatch: {cell.cell_id} {record.task_id}")
    status = receipt.get("trial_status")
    reliability = status == "reliability_failure"
    for key, expected_value in {"cell_kind": cell.cell_kind, "composition": cell.composition, "harness": cell.harness, "harness_version": cell.harness_version, "model_requested": cell.model_requested, "effort_requested": cell.effort_requested, "provider_route_resolved": cell.provider_route_resolved, "provider_effort_resolved": cell.provider_effort_resolved}.items():
        if key in receipt:
            if cell.cell_kind == "native_default" and key in {"provider_route_resolved", "provider_effort_resolved"}:
                if not isinstance(receipt[key], str) or not receipt[key].strip():
                    fail(f"resume native receipt identity is incomplete: {cell.cell_id} {key}")
            elif receipt[key] != expected_value:
                fail(f"resume receipt cell identity mismatch: {cell.cell_id} {key}")
    for key, expected_value in {"composition_digest": cell.composition_digest, "adapter_digest": cell.adapter_digest, "mcp_digest": mcp_identity_digest(), "agent_kwargs_digest": agent_kwargs_identity_digest(cell.agent_kwargs), "agent_allowed_hosts_digest": agent_allowed_hosts_identity_digest(cell)}.items():
        if key in receipt and receipt[key] not in {expected_value, f"sha256:{expected_value}"}:
            fail(f"resume receipt digest identity mismatch: {cell.cell_id} {key}")
    for key, expected_value in {"gateway_digests": list(cell.gateway_digests), "gateway_dockerfile_digests": list(cell.gateway_dockerfile_digests), "compose_digests": list(cell.compose_digests)}.items():
        if key in receipt and receipt[key] != expected_value:
            fail(f"resume receipt enforcement identity mismatch: {cell.cell_id} {key}")
    for key, expected_value in {"context_manifest_digest": record.context_manifest_digest, "context_pack_digest": record.context_pack_digest}.items():
        if receipt.get(key) not in {expected_value, f"sha256:{expected_value}"}:
            fail(f"resume receipt context identity mismatch: {cell.cell_id} {record.task_id} {key}")
    if receipt.get("source_cluster") not in {None, record.source_cluster}:
        fail(f"resume receipt source identity mismatch: {cell.cell_id} {record.task_id}")
    if receipt.get("task_digest") not in {record.task_digest, f"sha256:{record.task_digest}"}:
        fail(f"resume receipt task digest mismatch: {cell.cell_id} {record.task_id}")
    if receipt.get("comparison_task_digest") not in {record.comparison_task_digest, f"sha256:{record.comparison_task_digest}"}:
        fail(f"resume receipt comparison identity mismatch: {cell.cell_id} {record.task_id}")
    if receipt.get("context_digest") not in {record.context_digest, f"sha256:{record.context_digest}"}:
        fail(f"resume receipt context digest mismatch: {cell.cell_id} {record.task_id}")
    if receipt.get("skill_digest") not in {record.skill_digest, f"sha256:{record.skill_digest}"}:
        fail(f"resume receipt skill digest mismatch: {cell.cell_id} {record.task_id}")
    if receipt.get("row_id") not in {None, cell.row_id, f"sha256:{cell.row_id}" if cell.row_id else None}:
        fail(f"resume receipt row identity mismatch: {cell.cell_id}")
    if receipt.get("cohort_id") not in {None, cell.cohort_id, f"sha256:{cell.cohort_id}" if cell.cohort_id else None}:
        fail(f"resume receipt cohort identity mismatch: {cell.cell_id}")
    if receipt.get("profile_digest") not in {None, cell.profile_digest, f"sha256:{cell.profile_digest}"}:
        fail(f"resume receipt profile identity mismatch: {cell.cell_id}")
    if trusted is None and not reliability:
        fail(f"resume quality receipt trust is unavailable: {cell.cell_id} {record.task_id}")
    if trusted is not None and int(trusted) != 1 and not (int(trusted) == 0 and reliability):
        fail(f"resume receipt trust is invalid: {cell.cell_id} {record.task_id}")
    task_exchange = confined_path(root, "exchange", cell.cell_id, record.task_id)
    allowed_names = {"request.json", "result.json", "trial.json", "grader.json"}
    names = {path.name for path in task_exchange.iterdir()} if task_exchange.is_dir() else set()
    if not names.issubset(allowed_names):
        fail(f"resume exchange contains conflicting artifacts: {cell.cell_id} {record.task_id}")
    for key in ("runner_exchange_request_ref", "runner_exchange_result_ref"):
        reference = receipt.get(key)
        if reference is not None:
            _verify_content_ref(root, reference, key)
    for key, name in (("request_ref", "request.json"), ("result_ref", "result.json")):
        reference = receipt.get(key)
        if reference is not None:
            path = task_exchange / name
            if not path.is_file() or reference != f"sha256:{bytes_digest(path.read_bytes())}@{path.relative_to(root).as_posix()}":
                fail(f"resume canonical reference mismatch: {cell.cell_id} {record.task_id} {key}")
    for name in ("request.json", "result.json", "trial.json"):
        if not (task_exchange / name).is_file():
            fail(f"resume receipt artifacts are incomplete: {cell.cell_id} {record.task_id}")
    try:
        request = json.loads((task_exchange / "request.json").read_text(encoding="utf-8"))
        result = json.loads((task_exchange / "result.json").read_text(encoding="utf-8"))
        trial = json.loads((task_exchange / "trial.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"resume exchange artifact is invalid: {cell.cell_id} {record.task_id}: {error}")
    expected_run = f"{CAMPAIGN_ID}--{cell.cell_id}--{record.task_id}"
    expected_exchange = f"{expected_run}--{record.task_id}"
    if not isinstance(request, dict) or request.get("schema_version") != "crucible.runner_exchange_request.v1" or request.get("task_id") != record.task_id or request.get("cell_id") != cell.cell_id or request.get("cell_run_id") != cell.cell_run_id or request.get("exchange_id") != expected_exchange:
        fail(f"resume request artifact identity mismatch: {cell.cell_id} {record.task_id}")
    if not isinstance(result, dict) or result.get("schema_version") != "crucible.runner_exchange_result.v1" or result.get("exchange_id") != expected_exchange or result.get("cell_id") != cell.cell_id or result.get("cell_run_id") != cell.cell_run_id:
        fail(f"resume result artifact identity mismatch: {cell.cell_id} {record.task_id}")
    if not isinstance(trial, dict) or trial.get("schema_version") != "harness_census.trial_receipt.v1" or trial.get("campaign_id") != CAMPAIGN_ID or trial.get("cell_id") != cell.cell_id or trial.get("cell_run_id") != cell.cell_run_id or trial.get("task_name") != record.task_id or trial.get("trial_id") != f"{cell.cell_id}--{record.task_id}":
        fail(f"resume trial artifact identity mismatch: {cell.cell_id} {record.task_id}")
    singular_digests = {"dockerfile_digest": record.dockerfile_digest, "gateway_digest": record.gateway_digest, "gateway_dockerfile_digest": record.gateway_dockerfile_digest, "compose_digest": record.compose_digest}
    for artifact_name, artifact in (("request", request), ("result", result), ("trial", trial)):
        if any(artifact.get(key) not in {expected, f"sha256:{expected}"} for key, expected in singular_digests.items()):
            fail(f"resume {artifact_name} task artifact identity mismatch: {cell.cell_id} {record.task_id}")
    observation: dict[str, str] | None = None
    if not reliability:
        if not (task_exchange / "grader.json").is_file():
            fail(f"resume quality receipt is missing grader artifact: {cell.cell_id} {record.task_id}")
        try:
            grader = json.loads((task_exchange / "grader.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            fail(f"resume grader artifact is invalid: {cell.cell_id} {record.task_id}: {error}")
        if not isinstance(grader, dict) or grader.get("schema_version") != "harness_census.grader_receipt.v1" or grader.get("campaign_id") != CAMPAIGN_ID or grader.get("task_id") != record.task_id or grader.get("trial_id") != f"{cell.cell_id}--{record.task_id}" or any(grader.get(key) not in {expected, f"sha256:{expected}" if expected else None} for key, expected in {"row_id": cell.row_id, "cohort_id": cell.cohort_id, "baseline_id": cell.baseline_id, "profile_digest": cell.profile_digest}.items()) or grader.get("grader_digest") not in {record.grader_digest, f"sha256:{record.grader_digest}"} or grader.get("grader_identity") != "harness_census_deterministic" or not isinstance(grader.get("hard_pass"), bool) or isinstance(grader.get("task_points"), bool) or not isinstance(grader.get("task_points"), (int, float)) or not 0.0 <= float(grader.get("task_points")) <= 1.0:
            fail(f"resume grader artifact identity mismatch: {cell.cell_id} {record.task_id}")
        grader_ref = receipt.get("grader_receipt_ref")
        if grader_ref is not None and _verify_content_ref(root, grader_ref, "grader_receipt_ref") != task_exchange / "grader.json":
            fail(f"resume grader receipt reference mismatch: {cell.cell_id} {record.task_id}")
        expected_hard_pass = status == "success"
        if grader.get("hard_pass") != expected_hard_pass or receipt.get("hard_pass") != expected_hard_pass or receipt.get("task_points") != grader.get("task_points"):
            fail(f"resume receipt score disagrees with grader: {cell.cell_id} {record.task_id}")
        attestation, _ = _receipt_attestation(root, cell, record, receipt)
        tool_manifest = attestation.get("tool_manifest_digest")
        config_digest = attestation.get("config_digest")
        receipt_tool = receipt.get("tool_manifest_digest")
        if isinstance(tool_manifest, str) and tool_manifest and receipt_tool not in {tool_manifest, f"sha256:{tool_manifest}"}:
            fail(f"resume receipt tool manifest mismatch: {cell.cell_id} {record.task_id}")
        if isinstance(receipt_tool, str) and receipt_tool and not _valid_digest(receipt_tool.removeprefix("sha256:")):
            fail(f"resume receipt tool manifest is invalid: {cell.cell_id} {record.task_id}")
        if isinstance(config_digest, str) and isinstance(tool_manifest, str) and config_digest and tool_manifest:
            expected_system = cell.observed_system_identity(config_digest, tool_manifest)
            if receipt.get("system_identity") not in {expected_system, f"sha256:{expected_system}"}:
                fail(f"resume receipt system identity mismatch: {cell.cell_id} {record.task_id}")
            if cell.cell_kind == "native_default":
                route = receipt.get("provider_route_resolved")
                effort = receipt.get("provider_effort_resolved")
                effort_source = receipt.get("effort_source")
                if not all(isinstance(value, str) and value.strip() for value in (route, effort, effort_source)):
                    fail(f"resume native receipt identity is incomplete: {cell.cell_id} {record.task_id}")
                observation = {"model": str(route), "effort": str(effort), "effort_source": str(effort_source), "tool": tool_manifest, "config": config_digest}
    else:
        for key in ("failure_class", "failure_stage", "failure_code"):
            if not isinstance(receipt.get(key), str) or not receipt[key]:
                fail(f"resume reliability receipt is missing {key}: {cell.cell_id} {record.task_id}")
        detail_ref = receipt.get("failure_detail_ref")
        if detail_ref is not None:
            _verify_content_ref(root, detail_ref, "failure_detail_ref")
    transcript_ref = receipt.get("transcript_ref")
    if transcript_ref is not None:
        _verify_content_ref(root, transcript_ref, "transcript_ref")
    for value in receipt.get("evidence_refs", []):
        _verify_content_ref(root, value, "evidence ref")
    return reliability, observation


def _derive_cell_result(root: Path, cell: Cell, stage_digest: str, by_task: dict[str, tuple[dict[str, object], int | None]], resolved: Cell | None) -> dict[str, object]:
    cell_dir_prefix = f"cells/{cell.cell_id}/"
    observed_models: list[str] = []
    observed_efforts: list[str] = []
    observed_tools: list[str] = []
    observed_configs: list[str] = []
    observed_systems: list[str] = []
    attestations: list[dict[str, object]] = []
    attestation_digests: list[str] = []
    compact_receipts: list[dict[str, object]] = []
    for record in cell.task_records:
        receipt, _ = by_task[record.task_id]
        attestation, attestation_path = _receipt_attestation(root, cell, record, receipt)
        tool_manifest = attestation.get("tool_manifest_digest")
        config_digest = attestation.get("config_digest")
        if isinstance(tool_manifest, str) and tool_manifest:
            observed_tools.append(tool_manifest)
        if isinstance(config_digest, str) and config_digest:
            observed_configs.append(config_digest)
            if isinstance(tool_manifest, str) and tool_manifest:
                observed_systems.append(cell.observed_system_identity(config_digest, tool_manifest))
        observed = attestation.get("observed_identities")
        model = observed[0] if isinstance(observed, list) and len(observed) == 1 and isinstance(observed[0], str) else None
        if isinstance(model, str) and model:
            observed_models.append(model)
        effort = attestation.get("effort")
        if isinstance(effort, str) and effort:
            observed_efforts.append(effort)
        transcript_ref = receipt.get("transcript_ref")
        if isinstance(transcript_ref, str) and transcript_ref:
            transcript_cell_ref = transcript_ref.split("@", 1)[1].removeprefix(cell_dir_prefix)
        else:
            transcript_cell_ref = None
        attestation_ref = attestation_path.removeprefix(cell_dir_prefix)
        attestation_path_obj = confined_path(root, *attestation_path.split("/"))
        attestations.append({"task_id": record.task_id, "attestation_ref": attestation_ref, "attestation_digest": bytes_digest(attestation_path_obj.read_bytes()), "transcript_ref": transcript_cell_ref, "record": attestation})
        attestation_digests.append(attestations[-1]["attestation_digest"])
        compact = {key: receipt[key] for key in COMPACT_RECEIPT_KEYS if key in receipt and isinstance(receipt[key], (str, int, float, bool))}
        compact["receipt_digest"] = digest(compact)
        compact_receipts.append(compact)
    summary_cell = resolved if resolved is not None else cell
    return {"schema_version": "harness_census.normalized_result.v1", "campaign_id": CAMPAIGN_ID, "cell_id": cell.cell_id, "cell_run_id": cell.cell_run_id, "task_set_digest": cell.task_set_digest, "task_set_size": cell.task_set_size, "retry_policy_digest": cell.retry_policy_digest, "agent_kwargs_base_digest": cell.agent_kwargs_base_digest, "stage_manifest_digest": stage_digest, "return_code": None, "reconstructed": True, "model_requested": cell.model_requested, "effort_requested": cell.effort_requested, "provider_route_resolved": summary_cell.provider_route_resolved, "provider_effort_resolved": summary_cell.provider_effort_resolved, "response_model": observed_models[0] if len(observed_models) == 1 else None, "observed_models": sorted(set(observed_models)), "response_effort": observed_efforts[0] if len(observed_efforts) == 1 else None, "observed_efforts": sorted(set(observed_efforts)), "observed_tool_manifest_digests": sorted(set(observed_tools)), "observed_config_digests": sorted(set(observed_configs)), "observed_system_identities": sorted(set(observed_systems)), "effort_source": summary_cell.effort_source, "network_mode": cell.network_mode, "transport_network_mode": cell.transport_network_mode, "network_enforcement": cell.network_enforcement, "task_network_enforcement": cell.task_network_enforcement, "row_id": cell.row_id, "cohort_id": cell.cohort_id, "baseline_id": summary_cell.baseline_id, "profile_digest": cell.profile_digest, "agent_kwargs": dict(cell.agent_kwargs), "agent_allowed_hosts": list(cell.agent_allowed_hosts), "attestations": attestations, "attestation_digests": sorted(attestation_digests), "runner_exchange_receipts": compact_receipts}


def _reconcile_cell_result(root: Path, cell: Cell, stage_digest: str, by_task: dict[str, tuple[dict[str, object], int | None]], resolved: Cell | None) -> None:
    expected = _derive_cell_result(root, cell, stage_digest, by_task, resolved)
    result_path = confined_path(root, "cells", cell.cell_id, "result.json")
    if not result_path.is_file():
        write_json(result_path, expected)
        return
    try:
        stored = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"resume completed cell result is invalid: {cell.cell_id}: {error}")
    if not isinstance(stored, dict) or stored.get("cell_id") != cell.cell_id or stored.get("stage_manifest_digest") != stage_digest or stored.get("task_set_digest") != cell.task_set_digest:
        fail(f"resume completed cell result identity mismatch: {cell.cell_id}")
    derivable = {"schema_version", "campaign_id", "cell_id", "cell_run_id", "task_set_digest", "task_set_size", "retry_policy_digest", "agent_kwargs_base_digest", "stage_manifest_digest", "model_requested", "effort_requested", "provider_route_resolved", "provider_effort_resolved", "response_model", "observed_models", "response_effort", "observed_efforts", "observed_tool_manifest_digests", "observed_config_digests", "observed_system_identities", "effort_source", "network_mode", "transport_network_mode", "network_enforcement", "task_network_enforcement", "row_id", "cohort_id", "baseline_id", "profile_digest", "agent_kwargs", "agent_allowed_hosts", "attestations", "attestation_digests", "runner_exchange_receipts"}
    if {key: stored.get(key) for key in derivable} != {key: expected.get(key) for key in derivable}:
        fail(f"resume completed cell result is stale or mismatched: {cell.cell_id}")

def resolve_resume_cell(root: Path, cell: Cell, stage_digest: str) -> Cell:
    if cell.cell_kind != "native_default":
        return cell
    rows = _receipt_rows(root, cell)
    by_task: dict[str, tuple[dict[str, object], int | None]] = {}
    for receipt, trusted in rows:
        task_id = receipt.get("task_id") or receipt.get("task_name")
        if not isinstance(task_id, str) or task_id in by_task:
            fail(f"resume cell has duplicate or missing receipt task identity: {cell.cell_id}")
        by_task[task_id] = (receipt, trusted)
    observations: list[dict[str, str]] = []
    for record in cell.task_records:
        if record.task_id not in by_task:
            continue
        reliability, observation = _verified_task_receipt(root, cell, record, stage_digest, *by_task[record.task_id])
        if not reliability and observation is not None:
            observations.append(observation)
    if len(observations) != len(cell.task_records):
        return cell
    if len({tuple(sorted(observation.items())) for observation in observations}) != 1:
        fail(f"resume native receipts disagree on observed identity: {cell.cell_id}")
    observation = observations[0]
    resolved = cell.resolve_native(observation["model"], observation["effort"], observation["effort_source"], observation["tool"], observation["config"])
    for receipt, _ in by_task.values():
        baseline = receipt.get("baseline_id")
        if baseline is not None and baseline not in {resolved.baseline_id, f"sha256:{resolved.baseline_id}"}:
            fail(f"resume native receipt baseline mismatch: {cell.cell_id}")
    return resolved

def _reconcile_native_baseline(root: Path, cell: Cell, stage_digest: str, resolved: Cell, observation: dict[str, str], by_task: dict[str, tuple[dict[str, object], int | None]]) -> None:
    receipt_digests = [
        digest({key: receipt[key] for key in COMPACT_RECEIPT_KEYS if key in receipt and isinstance(receipt[key], (str, int, float, bool))})
        for receipt, _ in by_task.values()
    ]
    expected = {
        "schema_version": "harness_census.native_baseline_summary.v1",
        "campaign_id": CAMPAIGN_ID,
        "stage_manifest_digest": stage_digest,
        "cell_id": cell.cell_id,
        "cell_run_id": cell.cell_run_id,
        "baseline_id": resolved.baseline_id,
        "harness": cell.harness,
        "harness_version": cell.harness_version,
        "profile_digest": cell.profile_digest,
        "task_set_digest": cell.task_set_digest,
        "observed_model": observation["model"],
        "observed_effort": observation["effort"],
        "effort_source": observation["effort_source"],
        "tool_manifest_digest": observation["tool"],
        "config_digest": observation["config"],
        "system_identity": cell.observed_system_identity(observation["config"], observation["tool"]),
        "receipt_digests": receipt_digests,
        "status": "valid",
    }
    summary_path = confined_path(root, "baselines", str(resolved.baseline_id), "summary.json")
    if not summary_path.is_file():
        write_json(summary_path, expected)
        return
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        fail(f"resume native baseline summary is invalid: {cell.cell_id}: {error}")
    if not isinstance(summary, dict) or any(summary.get(key) != value for key, value in expected.items() if key != "receipt_digests") or sorted(summary.get("receipt_digests", [])) != sorted(receipt_digests):
        fail(f"resume native baseline summary identity mismatch: {cell.cell_id}")


def cell_receipt_state(root: Path, cell: Cell, stage_digest: str, expected_stage_digest: str | None = None) -> str:
    rows = _receipt_rows(root, cell)
    by_task: dict[str, tuple[dict[str, object], int | None]] = {}
    for receipt, trusted in rows:
        task_id = receipt.get("task_id") or receipt.get("task_name")
        if not isinstance(task_id, str) or task_id in by_task:
            fail(f"resume cell has duplicate or missing receipt task identity: {cell.cell_id}")
        by_task[task_id] = (receipt, trusted)
    expected_tasks = {record.task_id for record in cell.task_records}
    cell_dir = confined_path(root, "cells", cell.cell_id)
    exchange_dir = confined_path(root, "exchange", cell.cell_id)
    if expected_stage_digest is not None and cell_stage_digest(cell_dir, include_workspace=False) != expected_stage_digest:
        fail(f"resume staged bytes changed for cell: {cell.cell_id}")
    runtime_present = (cell_dir / "result.json").is_file() or (cell_dir / "results").is_dir() or exchange_dir.is_dir()
    if not rows and not runtime_present:
        return "absent"
    if not rows:
        return "partial"
    exchange_names = {path.name for path in exchange_dir.iterdir() if path.is_dir()} if exchange_dir.is_dir() else set()
    if not exchange_names.issubset(expected_tasks):
        fail(f"resume cell exchange task set is conflicting: {cell.cell_id}")
    reliability = False
    observations: list[dict[str, str]] = []
    for record in cell.task_records:
        if record.task_id not in by_task:
            continue
        receipt, trusted = by_task[record.task_id]
        task_reliability, observation = _verified_task_receipt(root, cell, record, stage_digest, receipt, trusted)
        reliability = reliability or task_reliability
        if observation is not None:
            observations.append(observation)
    if set(by_task) != expected_tasks or len(rows) != len(expected_tasks):
        return "invalid" if reliability else "partial"
    resolved: Cell | None = None
    if cell.cell_kind == "native_default" and not reliability:
        if len(observations) != len(cell.task_records):
            fail(f"resume native observation is incomplete: {cell.cell_id}")
        if len({tuple(sorted(observation.items())) for observation in observations}) != 1:
            fail(f"resume native receipts disagree on observation: {cell.cell_id}")
        observation = observations[0]
        resolved = cell.resolve_native(observation["model"], observation["effort"], observation["effort_source"], observation["tool"], observation["config"])
        for receipt, _ in by_task.values():
            baseline = receipt.get("baseline_id")
            if baseline is not None and baseline not in {resolved.baseline_id, f"sha256:{resolved.baseline_id}"}:
                fail(f"resume native receipt baseline mismatch: {cell.cell_id}")
        _reconcile_native_baseline(root, cell, stage_digest, resolved, observation, by_task)
    _reconcile_cell_result(root, cell, stage_digest, by_task, resolved)
    return "invalid" if reliability else "complete"


def pending_task_ids(root: Path, cell: Cell) -> list[str]:
    rows = _receipt_rows(root, cell)
    verified = {receipt.get("task_id") or receipt.get("task_name") for receipt, _ in rows}
    return [record.task_id for record in cell.task_records if record.task_id not in verified]
def receipt_task_ids(root: Path, cell: Cell) -> list[str]:
    expected = {record.task_id for record in cell.task_records}
    rows = _receipt_rows(root, cell)
    task_ids: list[str] = []
    for receipt, _ in rows:
        task_id = receipt.get("task_id") or receipt.get("task_name")
        if not isinstance(task_id, str) or task_id not in expected or task_id in task_ids:
            fail(f"resume cell has invalid receipt task identity: {cell.cell_id}")
        task_ids.append(task_id)
    return sorted(task_ids)


def resume_staged_cells(root: Path, source_root: Path, adapter_root: Path, prime_source: Path) -> tuple[tuple[Cell, ...], dict[str, str], dict[str, str], dict[str, str]]:
    assets, composition_digests = load_compositions()
    with tempfile.TemporaryDirectory(prefix="harness-census-resume-") as temporary:
        staged = Path(temporary)
        prime_package = stage_prime_package(staged, prime_source)
        expected = build_cells(staged, assets, composition_digests, source_root, adapter_root, prime_package)
        write_json(staged / "prime-package.json", {key: prime_package[key] for key in ("package", "version", "source_kind", "digest")})
        write_harbor_wrapper(staged)
        expected_digest = staged_bytes_digest(staged)
        expected_cell_digests = {cell.cell_id: cell_stage_digest(cell.cell_dir, include_workspace=False) for cell in expected}
    if staged_bytes_digest(root) != expected_digest:
        fail("immutable staged bytes do not match the frozen campaign")
    cells = tuple(replace(cell, cell_dir=root / "cells" / cell.cell_id, spec_path=root / "cells" / cell.cell_id / "eval.json") for cell in expected)
    return cells, composition_digests, prime_package, expected_cell_digests
