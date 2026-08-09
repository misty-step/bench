"""Shared census metadata, JSON, digest, and typed campaign models."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
import re
import tomllib
from typing import Mapping, NoReturn, TypedDict

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "benchmarks" / "harness-census-v0"
CAMPAIGN_ID = "harness-census-v0"
HARBOR_VERSION = "0.13.1"
BUN_VERSION = "1.3.14"
CONTROLLED_MODEL = "openrouter/deepseek/deepseek-v4-flash-0731"
CONTROLLED_EFFORT = "high"
AGENT_ALLOWED_HOSTS = ("mint.tail5f5eb4.ts.net",)
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
    {"model_requested": "openrouter/meta/muse-spark-1.2", "provider_route": "openrouter/meta/muse-spark-1.2", "efforts": ["minimal", "low", "medium", "high", "xhigh"]},
    {"model_requested": "openrouter/qwen/qwen3.8-max", "provider_route": "openrouter/qwen/qwen3.8-max", "efforts": ["minimal", "low", "medium", "high", "xhigh"]},
    {"model_requested": "openrouter/poolside/laguna-s-2.1", "provider_route": "openrouter/poolside/laguna-s-2.1", "efforts": ["minimal", "low", "medium", "high"]},
    {"model_requested": "openrouter/thinkingmachines/inkling", "provider_route": "openrouter/thinkingmachines/inkling", "efforts": ["minimal", "low", "medium", "max"]},
    {"model_requested": "openrouter/sakana/fugu-ultra", "provider_route": "openrouter/sakana/fugu-ultra", "efforts": ["high", "xhigh", "max"]},
    {"model_requested": "openrouter/nvidia/nemotron-3-ultra-550b-a55b", "provider_route": "openrouter/nvidia/nemotron-3-ultra-550b-a55b", "efforts": ["medium", "high"]},
    {"model_requested": "openrouter/minimax/minimax-m3", "provider_route": "openrouter/minimax/minimax-m3", "efforts": ["minimal", "low", "medium", "high"]},
)


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
    manifest: Mapping[str, object]


@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    task_digest: str
    comparison_task_digest: str
    source_tree_digest: str
    grader_digest: str
    dockerfile_digest: str
    prime_package_digest: str | None
    task_dir: str
    allowed_paths: tuple[str, ...]
    immutable_paths: tuple[str, ...]
    network_mode: str


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
    prime_package_digest: str | None
    dockerfile_digests: tuple[str, ...]
    task_records: tuple[TaskRecord, ...]

    def resolve_native(self, model: str, effort: str, effort_source: str) -> Cell:
        baseline_id = digest({
            "campaign_id": CAMPAIGN_ID,
            "harness": self.harness,
            "harness_version": self.harness_version,
            "composition": self.composition,
            "model": model,
            "effort": effort,
            "effort_source": effort_source,
            "system_identity": f"{self.harness}@{self.harness_version}",
            "profile_digest": self.profile_digest,
            "task_digest": self.task_digest,
        })
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

def task_identity(task: Task, source_tree_digest: str, instruction_digest: str, task_manifest_digest: str, grader_digest: str, reference_patch_digest: str) -> str:
    return digest({"task": task.id, "source_repository": task.source_repository, "source_sha": task.source_sha, "reference_sha": task.reference_sha, "allowed_paths": list(task.allowed_paths), "immutable_paths": list(task.immutable_paths), "instruction_digest": instruction_digest, "task_manifest_digest": task_manifest_digest, "source_tree_digest": source_tree_digest, "grader_digest": grader_digest, "reference_patch_digest": reference_patch_digest})


def task_corpus_identity(task: Task, source_tree_digest: str, grader_digest: str, reference_patch_digest: str) -> str:
    return digest({"task": task.id, "source_repository": task.source_repository, "source_sha": task.source_sha, "reference_sha": task.reference_sha, "allowed_paths": list(task.allowed_paths), "immutable_paths": list(task.immutable_paths), "source_tree_digest": source_tree_digest, "grader_digest": grader_digest, "reference_patch_digest": reference_patch_digest})


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


def fail(message: str, prefix: str = "harness-census driver") -> NoReturn:
    raise SystemExit(f"{prefix}: {message}")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def verified_commit(value: str, label: str) -> str:
    if not SHA40.fullmatch(value):
        fail(f"{label} must be a full lowercase 40-hex commit")
    return value


def load_tasks() -> dict[str, Task]:
    loaded: dict[str, Task] = {}
    for raw in MANIFEST["tasks"]:
        task_id = raw["id"]
        task_dir = PACKAGE / "tasks" / task_id
        if not task_dir.is_dir():
            fail(f"task directory missing: {task_id}")
        manifest = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
        for name in ("instruction.md", "grader.py", "reference.patch"):
            if not (task_dir / name).is_file():
                fail(f"task asset missing: {task_id}/{name}")
        loaded[task_id] = Task(task_id, raw["source_repository"], raw["source_sha"], raw["reference_sha"], tuple(raw["allowed_paths"]), tuple(raw["immutable_paths"]), raw["source_cluster"], task_dir, manifest)
    return loaded




def cell_summary(cell: Cell) -> dict[str, object]:
    return {"cell_id": cell.cell_id, "cell_run_id": cell.cell_run_id, "cell_kind": cell.cell_kind, "harness": cell.harness, "composition": cell.composition, "model_requested": cell.model_requested, "effort_requested": cell.effort_requested, "default_resolution_source": cell.default_resolution_source, "row_id": cell.row_id, "cohort_id": cell.cohort_id, "baseline_id": cell.baseline_id, "profile_digest": cell.profile_digest, "task_digest": cell.task_digest, "task_set_digest": cell.task_set_digest, "task_set_size": cell.task_set_size, "retry_policy_digest": cell.retry_policy_digest, "agent_kwargs_base_digest": cell.agent_kwargs_base_digest, "composition_digest": cell.composition_digest, "adapter_digest": cell.adapter_digest, "package_digest": cell.package_digest, "prime_package_digest": cell.prime_package_digest, "dockerfile_digests": list(cell.dockerfile_digests), "network_mode": cell.network_mode, "transport_network_mode": cell.transport_network_mode, "network_enforcement": cell.network_enforcement, "task_network_enforcement": cell.task_network_enforcement, "agent_kwargs": dict(cell.agent_kwargs), "agent_allowed_hosts": list(cell.agent_allowed_hosts)}
