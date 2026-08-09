"""Shared census metadata, JSON, digest, and typed campaign models."""
from __future__ import annotations

import hashlib
import json
import math
import os
import stat
from dataclasses import dataclass, replace
from fnmatch import fnmatchcase
from pathlib import Path
import re
import tomllib
from typing import Mapping, NoReturn, TypedDict

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "benchmarks" / "harness-census-v0"
CAMPAIGN_ID = "harness-census-v0"
NODE_IMAGE = "node:22.19.0-bookworm-slim@sha256:4a4884e8a44826194dff92ba316264f392056cbe243dcc9fd3551e71cea02b90"
GO_IMAGE = "golang:1.26.5-bookworm@sha256:6c5605ab3a9a9fb3c4eafe5b3d63cdbf3881caf113262b67862547b54a9db599"
RUST_IMAGE = "rust:1.97.1-bookworm@sha256:14bc9c5966e7b3a385794b3d5389a8765668342025fbcc7b2e3d2866ac4bd8c3"
GO_VERSION = "1.26.5"
RUST_VERSION = "1.97.1"
CARGO_VERSION = "1.97.1"
BUN_VERSION = "1.3.14"
HARBOR_VERSION = "0.13.1"
CONTROLLED_MODEL = "openrouter/anthropic/claude-opus-5"
CONTROLLED_EFFORT = "high"
AGENT_ALLOWED_HOSTS = ("mint-gateway",)
SHA40 = re.compile(r"^[0-9a-f]{40}$")
MANIFEST = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
NETWORK_POLICY = MANIFEST["network_policy"]
CONTROLLED_NETWORK_MODE = NETWORK_POLICY["controlled"]["network_mode"]
CONTROLLED_NETWORK_ENFORCEMENT = NETWORK_POLICY["controlled"]["network_enforcement"]
NATIVE_NETWORK_MODE = NETWORK_POLICY["native_default"]["network_mode"]
NATIVE_NETWORK_ENFORCEMENT = NETWORK_POLICY["native_default"]["network_enforcement"]
CONTROLLED_TRANSPORT_NETWORK_MODE = NETWORK_POLICY["controlled"]["transport_network_mode"]
CONTROLLED_TASK_NETWORK_ENFORCEMENT = NETWORK_POLICY["controlled"]["task_network_enforcement"]
NATIVE_TRANSPORT_NETWORK_MODE = NETWORK_POLICY["native_default"]["transport_network_mode"]
NATIVE_TASK_NETWORK_ENFORCEMENT = NETWORK_POLICY["native_default"]["task_network_enforcement"]


class RosterEntry(TypedDict):
    model_requested: str
    provider_route: str | None
    efforts: list[str]


ROSTER: tuple[RosterEntry, ...] = (
    {"model_requested": "openai-codex/gpt-5.6-sol", "provider_route": "openai-codex/gpt-5.6-sol", "efforts": ["low", "medium", "high", "xhigh", "max"]},
    {"model_requested": "openai-codex/gpt-5.6-terra", "provider_route": "openai-codex/gpt-5.6-terra", "efforts": ["low", "medium", "high", "xhigh", "max"]},
    {"model_requested": "openai-codex/gpt-5.6-luna", "provider_route": "openai-codex/gpt-5.6-luna", "efforts": ["low", "medium", "high", "xhigh", "max"]},
    {"model_requested": "openrouter/deepseek/deepseek-v4-flash-0731", "provider_route": "openrouter/deepseek/deepseek-v4-flash-0731", "efforts": ["low", "high", "max"]},
    {"model_requested": "google-antigravity/gemini-3.6-flash", "provider_route": "google-antigravity/gemini-3.6-flash", "efforts": ["minimal", "low", "medium", "high"]},
    {"model_requested": "google-antigravity/gemini-3.5-flash-lite", "provider_route": None, "efforts": []},
    {"model_requested": "xai-oauth/grok-4.5", "provider_route": "xai-oauth/grok-4.5", "efforts": ["minimal", "low", "medium", "high", "xhigh"]},
    {"model_requested": "openrouter/zai/glm-5.2", "provider_route": "openrouter/z-ai/glm-5.2", "efforts": ["minimal", "low", "medium", "high", "xhigh"]},
    {"model_requested": "kimi-code/k3", "provider_route": "kimi-code/k3", "efforts": ["low", "high", "max"]},
    {"model_requested": "anthropic/claude-fable-5", "provider_route": "anthropic/claude-fable-5", "efforts": ["low", "medium", "high", "xhigh", "max"]},
    {"model_requested": "anthropic/claude-opus-5", "provider_route": "anthropic/claude-opus-5", "efforts": ["low", "medium", "high", "xhigh", "max"]},
    {"model_requested": CONTROLLED_MODEL, "provider_route": CONTROLLED_MODEL, "efforts": [CONTROLLED_EFFORT]},
    {"model_requested": "openrouter/meta/muse-spark-1.2", "provider_route": "openrouter/meta/muse-spark-1.2", "efforts": ["minimal", "low", "medium", "high", "xhigh"]},
    {"model_requested": "openrouter/qwen/qwen3.8-max", "provider_route": "openrouter/qwen/qwen3.8-max", "efforts": ["minimal", "low", "medium", "high", "xhigh"]},
    {"model_requested": "openrouter/poolside/laguna-s-2.1", "provider_route": "openrouter/poolside/laguna-s-2.1", "efforts": ["minimal", "low", "medium", "high"]},
    {"model_requested": "openrouter/thinkingmachines/inkling", "provider_route": "openrouter/thinkingmachines/inkling", "efforts": ["minimal", "low", "medium", "max"]},
    {"model_requested": "openrouter/sakana/fugu-ultra", "provider_route": "openrouter/sakana/fugu-ultra", "efforts": ["high", "xhigh", "max"]},
    {"model_requested": "openrouter/nvidia/nemotron-3-ultra-550b-a55b", "provider_route": "openrouter/nvidia/nemotron-3-ultra-550b-a55b", "efforts": ["medium", "high"]},
    {"model_requested": "openrouter/minimax/minimax-m3", "provider_route": "openrouter/minimax/minimax-m3", "efforts": ["minimal", "low", "medium", "high"]},
)

COMPACT_RECEIPT_KEYS = ("run_id", "trial_id", "crucible_run_id", "receipt_id", "exchange_record_id", "trial_status", "failure_code", "request_ref", "result_ref", "grader_receipt_ref", "transcript_ref", "stage_manifest_digest", "row_id", "cohort_id", "baseline_id", "profile_digest", "context_digest", "context_manifest_digest", "context_pack_digest", "skill_digest", "skill_count", "dockerfile_digest", "gateway_digest", "gateway_dockerfile_digest", "compose_digest")


@dataclass(frozen=True)
class HarnessSpec:
    id: str
    version: str
    adapter: str
    package: str
    qualification_adapter: str


HARNESS_SPECS: tuple[HarnessSpec, ...] = (
    HarnessSpec("prime", "0.7.0", "harbor_agents.prime_agent:PrimeAgent", "prime-agent@0.7.0", "crucible.harbor_agents.prime_agent:PrimeAgent"),
    HarnessSpec("omp", "17.2.11", "harbor_agents.omp_agent:OmpAgent", "@oh-my-pi/pi-coding-agent@17.2.11", "crucible.harbor_agents.omp_agent:OmpAgent"),
    HarnessSpec("pi", "0.83.0", "harbor_agents.pi_agent:PiAgent", "@earendil-works/pi-coding-agent@0.83.0", "crucible.harbor_agents.pi_agent:PiAgent"),
)
HARNESSES = {spec.id: spec for spec in HARNESS_SPECS}


def qualification_harness_records() -> list[dict[str, object]]:
    return [{"id": spec.id, "version": spec.version, "adapter": spec.qualification_adapter} for spec in HARNESS_SPECS]


def runtime_harness_records() -> dict[str, dict[str, str]]:
    return {spec.id: {"version": spec.version, "adapter": spec.adapter, "package": spec.package} for spec in HARNESS_SPECS}

def campaign_matrix() -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for spec in HARNESS_SPECS:
        for composition in ("native_default", "controlled_raw", "controlled_enriched"):
            controlled = composition != "native_default"
            rows.append(
                {
                    "cell_id": f"{spec.id}-{composition}",
                    "harness": spec.id,
                    "composition": composition,
                    "model_requested": CONTROLLED_MODEL if controlled else None,
                    "effort_requested": CONTROLLED_EFFORT if controlled else None,
                }
            )
    return tuple(rows)


def model_roster_digest() -> str:
    return digest(ROSTER)


def harness_catalog_digest() -> str:
    return digest(runtime_harness_records())


@dataclass(frozen=True)
class Task:
    id: str
    source_repository: str
    source_sha: str
    reference_sha: str
    allowed_paths: tuple[str, ...]
    immutable_paths: tuple[str, ...]
    source_cluster: str
    task_dir: Path
    reference_hunk_checks: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ReferenceHunk:
    hunk_id: str
    header: str
    patch_digest: str
    grader_check: str


def parse_reference_hunks(patch: Path) -> tuple[tuple[str, str, str], ...]:
    lines = patch.read_text(encoding="utf-8").splitlines(keepends=True)
    hunks: list[tuple[str, str, str]] = []
    current_header: str | None = None
    current: list[str] = []
    for line in lines:
        if line.startswith("@@ "):
            if current_header is not None:
                hunk_id = f"hunk-{len(hunks) + 1:03d}"
                hunks.append((hunk_id, current_header, bytes_digest("".join(current).encode("utf-8"))))
            current_header = line.rstrip("\n")
            current = [line]
        elif current_header is not None:
            current.append(line)
    if current_header is not None:
        hunk_id = f"hunk-{len(hunks) + 1:03d}"
        hunks.append((hunk_id, current_header, bytes_digest("".join(current).encode("utf-8"))))
    if not hunks:
        fail(f"reference patch has no hunks: {patch}")
    return tuple(hunks)


def reference_hunk_mapping(task: Task) -> tuple[ReferenceHunk, ...]:
    declared = dict(task.reference_hunk_checks)
    parsed = parse_reference_hunks(task.task_dir / "reference.patch")
    actual_ids = {hunk_id for hunk_id, _, _ in parsed}
    declared_ids = set(declared)
    if declared_ids != actual_ids:
        missing = sorted(actual_ids - declared_ids)
        extra = sorted(declared_ids - actual_ids)
        fail(f"{task.id} reference hunk mapping is incomplete: missing={missing} extra={extra}")
    if any(not check.strip() for check in declared.values()):
        fail(f"{task.id} reference hunk mapping contains an unnamed grader check")
    return tuple(ReferenceHunk(hunk_id, header, patch_digest, declared[hunk_id]) for hunk_id, header, patch_digest in parsed)


def reference_hunk_map_digest(task: Task) -> str:
    return digest([
        {"hunk_id": hunk.hunk_id, "header": hunk.header, "patch_digest": hunk.patch_digest, "grader_check": hunk.grader_check}
        for hunk in reference_hunk_mapping(task)
    ])

@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    source_cluster: str
    task_digest: str
    comparison_task_digest: str
    grader_digest: str
    reference_hunk_map_digest: str
    dockerfile_digest: str
    gateway_digest: str
    gateway_dockerfile_digest: str
    compose_digest: str
    task_dir: str
    immutable_paths: tuple[str, ...]
    network_mode: str
    context_manifest_digest: str
    context_pack_digest: str
    skill_digest: str
    context_digest: str
    skill_count: int

@dataclass(frozen=True)
class Cell:
    cell_id: str
    cell_run_id: str
    task_set_digest: str
    task_set_size: int
    retry_policy_digest: str
    agent_kwargs_base_digest: str
    cell_dir: Path
    spec_path: Path
    cell_kind: str
    harness: str
    harness_version: str
    composition: str
    model_requested: str | None
    effort_requested: str | None
    provider_route_resolved: str | None
    provider_effort_resolved: str | None
    default_resolution_source: str | None
    effort_source: str | None
    row_id: str | None
    cohort_id: str | None
    baseline_id: str | None
    profile_digest: str
    agent_kwargs: Mapping[str, object]
    agent_allowed_hosts: tuple[str, ...]
    network_mode: str
    transport_network_mode: str
    network_enforcement: str
    task_network_enforcement: str
    task_digest: str
    composition_digest: str
    adapter_digest: str
    package_digest: str
    dockerfile_digests: tuple[str, ...]
    gateway_digests: tuple[str, ...]
    gateway_dockerfile_digests: tuple[str, ...]
    compose_digests: tuple[str, ...]
    task_records: tuple[TaskRecord, ...]

    def observed_system_identity(self, config_digest: str, tool_manifest_digest: str) -> str:
        return digest({"config_digest": config_digest, "tool_manifest_digest": tool_manifest_digest})

    def native_baseline_id(self, model: str, effort: str, effort_source: str, tool_manifest_digest: str, config_digest: str) -> str:
        system_identity = self.observed_system_identity(config_digest, tool_manifest_digest)
        return digest({
            "campaign_id": CAMPAIGN_ID,
            "harness": self.harness,
            "harness_version": self.harness_version,
            "composition": self.composition,
            "model": model,
            "effort": effort,
            "effort_source": effort_source,
            "tool_manifest_digest": tool_manifest_digest,
            "system_identity": system_identity,
            "profile_digest": self.profile_digest,
            "task_set_digest": self.task_set_digest,
        })

    def resolve_native(self, model: str, effort: str, effort_source: str, tool_manifest_digest: str, config_digest: str) -> Cell:
        baseline_id = self.native_baseline_id(model, effort, effort_source, tool_manifest_digest, config_digest)
        return replace(self, provider_route_resolved=model, provider_effort_resolved=effort, default_resolution_source="adapter_attestation:observed-native", effort_source=effort_source, baseline_id=baseline_id)


class Attestation(TypedDict, total=False):
    schema_version: str
    status: str
    adapter: str
    composition: str
    version: str
    observed_identities: list[str]
    expected_identity: str
    provider_route: str
    effort: str
    effort_source: str
    fallback_count: int
    turn_count: int
    tool_manifest_digest: str
    config_digest: str
    reason: str
    error: str
    message: str
    elapsed_seconds: float


class AttestationEntry(TypedDict):
    task_id: str
    trial_dir: Path
    attestation_path: Path
    attestation_ref: str
    attestation_digest: str
    transcript_ref: str | None
    transcript_path: Path | None
    record: Attestation


class HarborTrial(TypedDict, total=False):
    exception_info: object
    verifier_result: object


class Receipt(TypedDict, total=False):
    run_id: str
    trial_id: str
    crucible_run_id: str
    receipt_id: str
    exchange_record_id: str
    trial_status: str
    failure_code: str | None
    request_ref: str
    result_ref: str
    grader_receipt_ref: str | None
    transcript_ref: str | None
    stage_manifest_digest: str
    row_id: str | None
    cohort_id: str | None
    baseline_id: str | None
    profile_digest: str
    context_digest: str
    context_manifest_digest: str
    context_pack_digest: str
    skill_digest: str
    skill_count: int
    dockerfile_digest: str
    gateway_digest: str
    gateway_dockerfile_digest: str
    compose_digest: str


@dataclass(frozen=True)
class ExchangePaths:
    request: Path
    result: Path
    trial: Path
    grader: Path | None


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def harbor_reward_value(value: object) -> float | None:
    if not isinstance(value, dict) or set(value) != {"reward"}:
        return None
    reward = value["reward"]
    if isinstance(reward, bool) or not isinstance(reward, (int, float)):
        return None
    reward = float(reward)
    return reward if math.isfinite(reward) and 0.0 <= reward <= 1.0 else None

def mcp_identity_digest() -> str:
    return digest({"identity": "none", "tools": [], "network": "denied"})


def agent_kwargs_identity_digest(agent_kwargs: Mapping[str, object]) -> str:
    if any(not isinstance(value, str) for value in agent_kwargs.values()):
        fail("agent kwargs identity values must be strings")
    return digest(dict(agent_kwargs))


def cell_allowed_hosts(cell: Cell) -> list[str]:
    return list(cell.agent_allowed_hosts) if cell.network_enforcement == NATIVE_NETWORK_ENFORCEMENT else []


def agent_allowed_hosts_identity_digest(cell: Cell) -> str:
    return digest(cell_allowed_hosts(cell))


def confined_path(root: Path, *parts: str) -> Path:
    root = root.expanduser()
    try:
        root_info = os.lstat(root)
    except FileNotFoundError:
        fail(f"campaign root is missing: {root}")
    if stat.S_ISLNK(root_info.st_mode):
        fail(f"campaign root must not be a symlink: {root}")
    root_real = root.resolve()
    if not root_real.is_dir():
        fail(f"campaign root is not a directory: {root}")
    current = root_real
    for index, part in enumerate(parts):
        if not isinstance(part, str) or not part or part in {".", ".."} or Path(part).is_absolute() or "/" in part:
            fail(f"campaign path is unsafe: {'/'.join(parts)}")
        current = current / part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            fail(f"campaign path must not be a symlink: {current}")
        resolved = current.resolve()
        if not resolved.is_relative_to(root_real):
            fail(f"campaign path escapes root: {current}")
        if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
            fail(f"campaign path parent is not a directory: {current}")
    return current


def ensure_campaign_root(path: Path) -> Path:
    raw = path.expanduser()
    if raw.is_symlink():
        fail(f"campaign root must not be a symlink: {raw}")
    if raw.exists() and not raw.is_dir():
        fail(f"campaign root is not a directory: {raw}")
    raw.mkdir(parents=True, exist_ok=True)
    root = raw.resolve()
    confined_path(root)
    return root


def ensure_campaign_layout(root: Path) -> None:
    for name in ("stage-manifest.json", "campaign.json", "worker-preflight.json", "prime-package.json", "baselines", "context", "packages", "bin", "cells", "runs", "exchange"):
        confined_path(root, name)


def row_identity(model_requested: str | None, effort_requested: str | None, harness: str, composition: str) -> str:
    return digest([CAMPAIGN_ID, model_requested, effort_requested, harness, composition])


def cohort_identity(model_requested: str | None, effort_requested: str | None, provider_route_resolved: str | None, provider_effort_resolved: str | None) -> str:
    return digest([CAMPAIGN_ID, model_requested, effort_requested, provider_route_resolved, provider_effort_resolved])


def canonical_task_set_digest(pairs: list[tuple[str, str]]) -> str:
    normalized = sorted([[task_id, comparison.removeprefix("sha256:")] for task_id, comparison in pairs])
    return digest(normalized)

def task_identity(task: Task, source_tree_digest: str, instruction_digest: str, task_manifest_digest: str, grader_digest: str, reference_patch_digest: str, hunk_map_digest: str) -> str:
    return digest({"task": task.id, "source_repository": task.source_repository, "source_sha": task.source_sha, "reference_sha": task.reference_sha, "allowed_paths": list(task.allowed_paths), "immutable_paths": list(task.immutable_paths), "instruction_digest": instruction_digest, "task_manifest_digest": task_manifest_digest, "source_tree_digest": source_tree_digest, "grader_digest": grader_digest, "reference_patch_digest": reference_patch_digest, "reference_hunk_map_digest": hunk_map_digest})


def task_corpus_identity(task: Task, source_tree_digest: str, grader_digest: str, reference_patch_digest: str, hunk_map_digest: str) -> str:
    return digest({"task": task.id, "source_repository": task.source_repository, "source_sha": task.source_sha, "reference_sha": task.reference_sha, "allowed_paths": list(task.allowed_paths), "immutable_paths": list(task.immutable_paths), "source_tree_digest": source_tree_digest, "grader_digest": grader_digest, "reference_patch_digest": reference_patch_digest, "reference_hunk_map_digest": hunk_map_digest})


def bytes_digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_digest(path: Path) -> str:
    return bytes_digest(path.read_bytes())


def tree_files(root: Path, *, exclude_git: bool) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root).as_posix()
        if exclude_git and (name == ".git" or name.startswith(".git/")):
            continue
        if path.is_symlink():
            result[name] = b"SYMLINK:" + os.readlink(path).encode("utf-8")
        elif path.is_file():
            result[name] = path.read_bytes()
    return result


def tree_digest(root: Path, *, exclude_git: bool) -> str:
    return digest([(name, bytes_digest(value)) for name, value in tree_files(root, exclude_git=exclude_git).items()])


def _skip_match(name: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatchcase(name, pattern) or name.startswith(pattern + "/") for pattern in patterns)


def campaign_tree_files(root: Path, *, skip: tuple[str, ...] = ()) -> dict[str, bytes]:
    try:
        root_info = os.lstat(root)
    except FileNotFoundError:
        fail(f"campaign tree is missing: {root}")
    if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
        fail(f"campaign tree root is unsafe: {root}")
    real = root.resolve()
    selected: dict[str, bytes] = {}
    for directory, dir_names, file_names in os.walk(root, topdown=True, followlinks=False):
        relative_dir = Path(directory).relative_to(root).as_posix()
        relative_dir = "" if relative_dir == "." else relative_dir
        keep_dirs: list[str] = []
        for name in dir_names:
            relative = f"{relative_dir}/{name}" if relative_dir else name
            if _skip_match(relative, skip):
                continue
            entry = Path(directory) / name
            try:
                info = os.lstat(entry)
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                fail(f"campaign tree contains an unsafe entry: {relative}")
            if not entry.resolve().is_relative_to(real):
                fail(f"campaign tree entry escapes root: {relative}")
            keep_dirs.append(name)
        dir_names[:] = keep_dirs
        for name in sorted(file_names):
            relative = f"{relative_dir}/{name}" if relative_dir else name
            if _skip_match(relative, skip):
                continue
            entry = Path(directory) / name
            try:
                info = os.lstat(entry)
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                fail(f"campaign tree contains an unsafe entry: {relative}")
            if not entry.resolve().is_relative_to(real):
                fail(f"campaign tree entry escapes root: {relative}")
            selected[relative] = entry.read_bytes()
    return selected


def fail(message: str, prefix: str = "harness-census driver") -> NoReturn:
    raise SystemExit(f"{prefix}: {message}")


def cell_stage_digest(cell_dir: Path, *, include_workspace: bool) -> str:
    selected: dict[str, bytes] = {}
    skip_prefixes = ["results", "request.json", "result.json", "tasks/*/environment/runtime-package/*"]
    if not include_workspace:
        skip_prefixes.append("tasks/*/environment/repo/*")
    for name, value in campaign_tree_files(cell_dir, skip=tuple(skip_prefixes)).items():
        parts = name.split("/")
        if parts[0] in {"results", "request.json", "result.json"}:
            continue
        if parts[0] == "tasks" and len(parts) >= 4 and parts[2:4] == ["environment", "repo"] and not include_workspace:
            continue
        selected[name] = value
    return digest([(name, bytes_digest(value)) for name, value in sorted(selected.items())])


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def verified_commit(value: str, label: str) -> str:
    if not SHA40.fullmatch(value):
        fail(f"{label} must be a full lowercase 40-hex commit")
    return value


def load_tasks() -> dict[str, Task]:
    loaded: dict[str, Task] = {}
    minimum_alternatives = int(MANIFEST.get("qualification", {}).get("alternatives_per_task_minimum", 2))
    for raw in MANIFEST["tasks"]:
        task_id = raw["id"]
        task_dir = PACKAGE / "tasks" / task_id
        if not task_dir.is_dir():
            fail(f"task directory missing: {task_id}")
        manifest = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
        for name in ("instruction.md", "grader.py", "reference.patch"):
            if not (task_dir / name).is_file():
                fail(f"task asset missing: {task_id}/{name}")
        alternatives = sorted((task_dir / "alternatives").glob("*.patch"))
        if len(alternatives) < minimum_alternatives:
            fail(f"{task_id} has {len(alternatives)} alternatives; minimum is {minimum_alternatives}")
        raw_mapping = raw.get("reference_hunk_checks")
        if not isinstance(raw_mapping, list):
            fail(f"{task_id} reference_hunk_checks must be a list")
        pairs: list[tuple[str, str]] = []
        for item in raw_mapping:
            if not isinstance(item, dict) or not isinstance(item.get("hunk_id"), str) or not isinstance(item.get("grader_check"), str):
                fail(f"{task_id} reference_hunk_checks has an invalid entry")
            pairs.append((item["hunk_id"], item["grader_check"]))
        if len({hunk_id for hunk_id, _ in pairs}) != len(pairs):
            fail(f"{task_id} reference_hunk_checks contains duplicate hunk IDs")
        task = Task(task_id, raw["source_repository"], raw["source_sha"], raw["reference_sha"], tuple(raw["allowed_paths"]), tuple(raw["immutable_paths"]), raw["source_cluster"], task_dir, tuple(pairs))
        reference_hunk_mapping(task)
        loaded[task_id] = task
    return loaded




def cell_summary(cell: Cell) -> dict[str, object]:
    return {
        "cell_id": cell.cell_id,
        "cell_run_id": cell.cell_run_id,
        "cell_kind": cell.cell_kind,
        "harness": cell.harness,
        "harness_version": cell.harness_version,
        "composition": cell.composition,
        "model_requested": cell.model_requested,
        "effort_requested": cell.effort_requested,
        "provider_route_resolved": cell.provider_route_resolved,
        "provider_effort_resolved": cell.provider_effort_resolved,
        "default_resolution_source": cell.default_resolution_source,
        "effort_source": cell.effort_source,
        "row_id": cell.row_id,
        "cohort_id": cell.cohort_id,
        "baseline_id": cell.baseline_id,
        "profile_digest": cell.profile_digest,
        "agent_kwargs_digest": agent_kwargs_identity_digest(cell.agent_kwargs),
        "agent_allowed_hosts_digest": agent_allowed_hosts_identity_digest(cell),
        "composition_digest": cell.composition_digest,
        "adapter_digest": cell.adapter_digest,
        "mcp_digest": mcp_identity_digest(),
        "task_digest": cell.task_digest,
        "task_set_digest": cell.task_set_digest,
        "task_set_size": cell.task_set_size,
        "retry_policy_digest": cell.retry_policy_digest,
        "agent_kwargs_base_digest": cell.agent_kwargs_base_digest,
        "task_context": [
            {
                "task_id": record.task_id,
                "task_digest": record.task_digest,
                "comparison_task_digest": record.comparison_task_digest,
                "reference_hunk_map_digest": record.reference_hunk_map_digest,
                "context_manifest_digest": record.context_manifest_digest,
                "context_pack_digest": record.context_pack_digest,
                "skill_digest": record.skill_digest,
                "context_digest": record.context_digest,
                "skill_count": record.skill_count,
            }
            for record in cell.task_records
        ],
        "compose_digests": list(cell.compose_digests),
        "network_mode": cell.network_mode,
        "transport_network_mode": cell.transport_network_mode,
        "network_enforcement": cell.network_enforcement,
        "task_network_enforcement": cell.task_network_enforcement,
        "agent_allowed_hosts": list(cell.agent_allowed_hosts),
    }
