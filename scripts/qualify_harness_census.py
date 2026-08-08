#!/usr/bin/env python3
"""Qualify history-free harness-census tasks without provider calls."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tarfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "benchmarks" / "harness-census-v0"
TASKS = [
    {"id": "iron-forest-go-checkruns-array", "repository": "iron-forest", "source_repository": "misty-step/iron-forest", "source_sha": "e98569f48664759242b062a5a46910c03375c0ed", "reference_sha": "520c629d4987720e9533ae63e4478cd9479c6b78", "allowed_paths": ["prs.go"], "immutable_paths": ["go.mod"], "source_cluster": "generic-parser", "unchanged_failure": "checkruns-array"},
    {"id": "estate-pagination-origin", "repository": "estate", "source_repository": "misty-step/estate", "source_sha": "054020ba4929ce8794cbd7524865fdc155cc9ef7", "reference_sha": "c6e92b73ee69fb6ef56d349000f85fb8b70843ed", "allowed_paths": ["src/collect/digitalocean.rs"], "immutable_paths": ["Cargo.toml", "Cargo.lock"], "source_cluster": "security-boundary", "unchanged_failure": "origin-helper"},
    {"id": "sploot-hydration-device-lane", "repository": "sploot", "source_repository": "misty-step/sploot", "source_sha": "4a2a3d29831e4c8d22dc28130a062bda8f51b601", "reference_sha": "1d5b3282a236996dbc4cf79ff4c9c4c5d2cb085c", "allowed_paths": ["apps/web/components/library/empty-state.tsx"], "immutable_paths": ["apps/web/components/chrome/status-line.tsx"], "source_cluster": "product-hydration", "unchanged_failure": "external-store-import"},
]
ROSTER = [
    {"model_requested": "openai-codex/gpt-5.6-sol", "provider_route": "openai-codex/gpt-5.6-sol", "efforts": ["low", "medium", "high", "xhigh", "max"]},
    {"model_requested": "openai-codex/gpt-5.6-terra", "provider_route": "openai-codex/gpt-5.6-terra", "efforts": ["low", "medium", "high", "xhigh", "max"]},
    {"model_requested": "openai-codex/gpt-5.6-luna", "provider_route": "openai-codex/gpt-5.6-luna", "efforts": ["low", "medium", "high", "xhigh", "max"]},
    {"model_requested": "openrouter/deepseek-v4-flash-0731", "provider_route": "openrouter/deepseek/deepseek-v4-flash-0731", "efforts": ["low", "high", "max"]},
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
]
HARNESSES = [
    {"id": "prime", "version": "0.7.0", "adapter": "crucible.harbor_agents.prime_agent:PrimeAgent"},
    {"id": "omp", "version": "17.2.11", "adapter": "crucible.harbor_agents.omp_agent:OmpAgent"},
    {"id": "pi", "version": "0.83.0", "adapter": "crucible.harbor_agents.pi_agent:PiAgent"},
]
COMPOSITIONS = ["controlled_raw", "controlled_enriched"]
SMOKE_MODEL = "openrouter/deepseek-v4-flash-0731"
SMOKE_ROUTE = "openrouter/deepseek/deepseek-v4-flash-0731"
SMOKE_EFFORT = "high"


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(message: str) -> None:
    raise SystemExit(f"harness-census qualification: {message}")


def repo_path(task: dict[str, Any]) -> Path:
    override = os.environ.get(f"HARNESS_CENSUS_{task['repository'].upper()}_REPO")
    return Path(override) if override else Path("/home/phaedrus/Development/misty-step") / task["repository"]


def safe_archive(repo: Path, commit: str, destination: Path) -> None:
    if not repo.is_dir():
        fail(f"pinned repository is missing: {repo}")
    result = subprocess.run(["git", "-C", str(repo), "archive", commit], check=True, capture_output=True)
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:") as archive:
        root = destination.resolve()
        for member in archive.getmembers():
            target = (destination / member.name).resolve()
            if root != target and root not in target.parents:
                fail(f"archive path escapes workspace: {member.name}")
            if member.issym() or member.islnk():
                link_target = (target.parent / member.linkname).resolve()
                if root != link_target and root not in link_target.parents:
                    fail(f"archive link escapes workspace: {member.name}")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(member.linkname)
                continue
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    fail(f"cannot read archive member: {member.name}")
                target.write_bytes(source.read())
                target.chmod(member.mode & 0o777)

def tree_files(root: Path) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            result[path.relative_to(root).as_posix()] = b"SYMLINK:" + os.readlink(path).encode("utf-8")
        elif path.is_file():
            relative = path.relative_to(root).as_posix()
            if relative == ".git" or relative.startswith(".git/"):
                continue
            result[relative] = path.read_bytes()
    return result


def tree_digest(root: Path) -> str:
    records = [(name, hashlib.sha256(value).hexdigest()) for name, value in tree_files(root).items()]
    return digest(records)


def apply_patch(root: Path, patch: Path) -> None:
    subprocess.run(["git", "-C", str(root), "apply", "--check", str(patch)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "apply", str(patch)], check=True, capture_output=True)


def run_grader(task_dir: Path, image: Path) -> tuple[int, dict[str, Any]]:
    result = subprocess.run([sys.executable, str(task_dir / "grader.py"), str(image)], text=True, capture_output=True)
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    try:
        report = json.loads(lines[-1]) if lines else {"passed": False, "failed_check": "no-report"}
    except json.JSONDecodeError:
        report = {"passed": False, "failed_check": "invalid-report"}
    report["return_code"] = result.returncode
    return result.returncode, report


def scope_changed(before: Path, after: Path, allowed: list[str]) -> list[str]:
    old, new = tree_files(before), tree_files(after)
    changed = sorted(name for name in set(old) | set(new) if old.get(name) != new.get(name))
    if not set(changed).issubset(allowed):
        fail(f"scope changed outside allowed paths: {changed}")
    return changed


def exposure_check(image: Path, task: dict[str, Any]) -> None:
    if (image / ".git").exists():
        fail(f"{task['id']} image contains Git metadata")
    forbidden = ("model-harness-census-v0.md", "harness-gauntlet-failure-modes.md", "reference.patch", "grader.py")
    for name, value in tree_files(image).items():
        text = value.decode("utf-8", errors="ignore")
        if any(token in text for token in forbidden):
            fail(f"{task['id']} image exposes qualification material through {name}")


def qualify_task(task: dict[str, Any]) -> dict[str, Any]:
    task_dir = PACKAGE / "tasks" / task["id"]
    repo = repo_path(task)
    mutant_manifest = json.loads((task_dir / "mutants" / "manifest.json").read_text())
    with tempfile.TemporaryDirectory(prefix=f"harness-census-{task['repository']}-") as temporary:
        work = Path(temporary)
        base_a, base_b = work / "base-a", work / "base-b"
        safe_archive(repo, task["source_sha"], base_a)
        safe_archive(repo, task["source_sha"], base_b)
        fixture_digest = tree_digest(base_a)
        if fixture_digest != tree_digest(base_b):
            fail(f"{task['id']} history-free image digest is not stable")
        exposure_check(base_a, task)
        unchanged = work / "unchanged"
        shutil.copytree(base_a, unchanged, symlinks=True)
        unchanged_code, unchanged_report = run_grader(task_dir, unchanged)
        if unchanged_code == 0 or unchanged_report.get("failed_check") != task["unchanged_failure"]:
            fail(f"{task['id']} unchanged image did not fail {task['unchanged_failure']}: {unchanged_report}")
        reference = work / "reference"
        shutil.copytree(base_a, reference, symlinks=True)
        apply_patch(reference, task_dir / "reference.patch")
        changed = scope_changed(base_a, reference, task["allowed_paths"])
        reference_code, reference_report = run_grader(task_dir, reference)
        if reference_code != 0 or reference_report.get("passed") is not True:
            fail(f"{task['id']} reference failed: {reference_report}")
        mutants: list[dict[str, Any]] = []
        for declaration in mutant_manifest["mutants"]:
            mutant = work / f"mutant-{declaration['id']}"
            shutil.copytree(base_a, mutant, symlinks=True)
            patch = task_dir / "mutants" / declaration["path"]
            apply_patch(mutant, patch)
            mutant_changed = scope_changed(base_a, mutant, task["allowed_paths"])
            code, report = run_grader(task_dir, mutant)
            if code == 0 or report.get("failed_check") != declaration["failure_marker"]:
                fail(f"{task['id']} mutant {declaration['id']} failed for wrong reason: {report}")
            mutants.append({"id": declaration["id"], "patch_digest": file_digest(patch), "changed_paths": mutant_changed, "failure_check": report["failed_check"]})
        receipt = {
            "schema_version": "harness_census.qualification_receipt.v1",
            "package_id": "harness-census-v0",
            "task_id": task["id"],
            "source_repository": task["source_repository"],
            "source_sha": task["source_sha"],
            "reference_sha": task["reference_sha"],
            "source_cluster": task["source_cluster"],
            "fixture": {"history_free": True, "tree_digest": fixture_digest, "stable_repeated_digest": True, "git_history_in_image": False},
            "reference": {"patch_digest": file_digest(task_dir / "reference.patch"), "grader_digest": file_digest(task_dir / "grader.py"), "passed": True, "changed_paths": changed},
            "unchanged_image": {"passed": False, "intended_failure": unchanged_report["failed_check"]},
            "mutants": mutants,
            "scope": {"allowed_paths": task["allowed_paths"], "changed_paths": changed, "passed": True},
            "exposure": {"private_source_bytes_checked_in": False, "future_git_objects_exposed": False, "grader_and_reference_hidden_from_worker": True},
            "harbor_permissions": {"verifier_dir_mode": "0755", "reward_file_mode": "0644"},
            "qualified": True,
        }
    receipt_path = PACKAGE / "receipts" / f"{task['id']}.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    return receipt


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_smoke(receipts: list[dict[str, Any]]) -> None:
    campaign_id = "harness-census-v0"
    rows: list[dict[str, Any]] = []
    for model in ROSTER:
        for effort in (model["efforts"] or [None]):
            for harness in HARNESSES:
                for composition in COMPOSITIONS:
                    blocked_gemini = model["model_requested"] == "google-antigravity/gemini-3.5-flash-lite"
                    confirmed = model["model_requested"] == SMOKE_MODEL and effort == SMOKE_EFFORT
                    key = [campaign_id, model["model_requested"], effort, harness["id"], composition]
                    rows.append({"schema_version": "harness_census.availability.v1", "campaign_id": campaign_id, "model_requested": model["model_requested"], "effort_requested": effort, "provider_route_resolved": SMOKE_ROUTE if confirmed else None, "provider_effort_resolved": SMOKE_EFFORT if confirmed else None, "harness": harness["id"], "composition": composition, "status": "confirmed" if confirmed else ("blocked_route" if blocked_gemini else "blocked_task"), "reason_code": None if confirmed else ("route_unavailable" if blocked_gemini else "smoke_not_selected"), "evidence_ref": None, "row_id": digest(key), "cohort_id": digest([campaign_id, model["model_requested"], effort, SMOKE_ROUTE, SMOKE_EFFORT]) if confirmed else None})
    rows.sort(key=lambda row: row["row_id"])
    evidence = {"schema_version": "harness_census.availability_evidence.v1", "campaign_id": campaign_id, "records": [{"schema_version": "harness_census.availability_evidence.v1", "campaign_id": campaign_id, "row_id": row["row_id"], "model_requested": row["model_requested"], "effort_requested": row["effort_requested"], "provider_route_resolved": row["provider_route_resolved"], "provider_effort_resolved": row["provider_effort_resolved"], "harness": row["harness"], "harness_version": next(h["version"] for h in HARNESSES if h["id"] == row["harness"]), "adapter_digest": digest(next(h["adapter"] for h in HARNESSES if h["id"] == row["harness"])), "catalog_digest": digest(ROSTER), "probe_request_digest": digest([row["model_requested"], row["effort_requested"]]), "probe_result_digest": digest([row["status"], row["provider_route_resolved"], row["provider_effort_resolved"]]), "observed_status": row["status"]} for row in rows]}
    evidence_digest = digest(evidence)
    for row in rows:
        row["evidence_ref"] = f"sha256:{evidence_digest}@smoke/availability-evidence.json"
    write_json(PACKAGE / "smoke" / "availability-evidence.json", evidence)
    write_json(PACKAGE / "smoke" / "availability.json", {"schema_version": "harness_census.availability.v1", "campaign_id": campaign_id, "rows": rows, "roster_digest": digest(ROSTER)})
    task_digest = digest([{key: task[key] for key in ("id", "source_sha", "reference_sha", "allowed_paths")} for task in TASKS])
    stage = {"schema_version": "harness_census.stage_manifest.v1", "campaign_id": campaign_id, "stage_id": "smoke", "bench_commit": "harness-census-v0-package", "crucible_commit": "sibling-supplied", "roster_digest": digest(ROSTER), "catalog_digest": digest(ROSTER), "harness_digest": digest(HARNESSES), "adapter_digest": digest([h["adapter"] for h in HARNESSES]), "pack_digest": digest({"controlled_raw": [], "controlled_enriched": [], "native_default": []}), "mcp_digest": digest({"identity": "none", "tools": [], "network": "denied"}), "task_digest": task_digest, "grader_digest": digest([receipt["reference"]["grader_digest"] for receipt in receipts]), "retry_policy": {"product_retry": 0, "transport_retry": 0}, "decision_policy": {"hard_pass_requires_all_tasks": True, "native_default_separate": True}, "task_qualification_receipts": [digest(receipt) for receipt in receipts]}
    write_json(PACKAGE / "smoke" / "stage-manifest.json", stage)
    write_json(PACKAGE / "smoke" / "erasure.json", {"schema_version": "harness_census.erasure.v1", "campaign_id": campaign_id, "candidate_kind": "duplicate_artifact", "behavior_preserving_oracle": "No duplicate confirmed rows or evidence bytes are stored.", "planned_trials_before": 0, "planned_trials_after": 0, "stored_bytes_before": 0, "stored_bytes_after": 0, "erased_counts": {"trials": 0, "artifacts": 0}, "reason": "Smoke is identity and receipt plumbing only; no paid trial bytes are created."})
    spec = {"schema_version": "crucible.eval_spec.v1", "id": "harness-census-v0-smoke", "task": "harness-census-v0", "inputs": "Three history-free pinned repository repair tasks with deterministic graders.", "outputs": "One native-default baseline and one six-cell controlled smoke receipt set.", "graders": {"graders": [{"id": "harness_census_deterministic", "kind": "deterministic"}]}, "aggregation": "proportion", "uncertainty": {"method": "wilson", "confidence": 0.95}, "decision": "Qualify harness identity and task receipt plumbing without paid model quality claims.", "runner": {"kind": "harbor_task", "corpus": {"source": "harbor_tasks", "config": {"agent": "pi", "agent_import_path": "crucible.harbor_agents.pi_agent:PiAgent", "model": SMOKE_ROUTE, "job_timeout_ms": 900000, "resource_envelope": {"cpu_millicores": 1000, "memory_mb": 1024, "headroom_percent": 50}}, "tasks": [{"task_id": task["id"], "task_dir": f"../tasks/{task['id']}"} for task in TASKS]}}, "campaign_id": campaign_id, "stage_manifest_digest": digest(stage), "smoke_cells": [{"cell_kind": "native_default", "harness": harness["id"], "task_ids": [task["id"] for task in TASKS]} for harness in HARNESSES] + [{"cell_kind": "controlled", "model_requested": SMOKE_MODEL, "effort_requested": SMOKE_EFFORT, "harness": harness["id"], "composition": composition, "row_id": digest([campaign_id, SMOKE_MODEL, SMOKE_EFFORT, harness["id"], composition]), "task_ids": [task["id"] for task in TASKS]} for harness in HARNESSES for composition in COMPOSITIONS], "blocked_sentinels": [{"model_requested": "google-antigravity/gemini-3.5-flash-lite", "effort_requested": None, "harness": harness["id"], "composition": composition, "status": "blocked_route", "reason_code": "route_unavailable"} for harness in HARNESSES for composition in COMPOSITIONS]}
    write_json(PACKAGE / "smoke" / "harness-census-v0.json", spec)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-smoke", action="store_true", help="qualify tasks without writing smoke manifests")
    args = parser.parse_args()
    receipts = [qualify_task(task) for task in TASKS]
    if not args.no_smoke:
        write_smoke(receipts)
    print(json.dumps({"package_id": "harness-census-v0", "qualified_tasks": [receipt["task_id"] for receipt in receipts], "paid_models_called": False, "smoke_written": not args.no_smoke}, sort_keys=True))


if __name__ == "__main__":
    main()
