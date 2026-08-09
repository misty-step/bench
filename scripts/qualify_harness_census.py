#!/usr/bin/env python3
"""Qualify history-free harness-census tasks without provider calls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Mapping

from harness_census_archive import archive_git_tree
from harness_census_common import (
    CAMPAIGN_ID, NETWORK_POLICY, PACKAGE, Task, campaign_matrix,
    digest, fail, file_digest, harness_catalog_digest, load_tasks, model_roster_digest,
    qualification_harness_records, task_identity, tree_digest, tree_files, write_json,
)
from harness_census_gateway import MINT_INTERNAL_BASE_URL, gateway_identity
from harness_census_staging import validate_stage_manifest

COMPOSITIONS = ("controlled_raw", "controlled_enriched")
TASKS = load_tasks()


def repo_path(source_root: Path, task: Task) -> Path:
    return source_root / task.source_repository.rsplit("/", 1)[-1]


def archive_task(repo: Path, commit: str, destination: Path) -> None:
    try:
        archive_git_tree(repo, commit, destination)
    except RuntimeError as error:
        fail(str(error), "harness-census qualification")


def apply_patch(root: Path, patch: Path) -> None:
    subprocess.run(["git", "-C", str(root), "apply", "--check", str(patch)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "apply", str(patch)], check=True, capture_output=True)


def run_grader(task: Task, image: Path) -> tuple[int, dict[str, object]]:
    result = subprocess.run([sys.executable, str(task.task_dir / "grader.py"), str(image)], text=True, capture_output=True, check=False)
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    try:
        report = json.loads(lines[-1]) if lines else {"passed": False, "failed_check": "no-report"}
    except json.JSONDecodeError:
        report = {"passed": False, "failed_check": "invalid-report"}
    if not isinstance(report, dict):
        report = {"passed": False, "failed_check": "invalid-report"}
    report["return_code"] = result.returncode
    return result.returncode, report


def infrastructure_failure(report: Mapping[str, object]) -> str | None:
    if report.get("failed_check") != "invalid-syntax":
        return None
    detail = str(report.get("detail", "")).lower()
    if "timed out" in detail or "compiling " in detail or "could not start" in detail:
        return "timeout" if "timed out" in detail else "setup"
    return None


def scope_changed(before: Path, after: Path, allowed: tuple[str, ...]) -> list[str]:
    old = tree_files(before, exclude_git=True)
    new = tree_files(after, exclude_git=True)
    changed = sorted(name for name in set(old) | set(new) if old.get(name) != new.get(name))
    if not set(changed).issubset(allowed):
        fail(f"scope changed outside allowed paths: {changed}", "harness-census qualification")
    return changed


def exposure_check(image: Path, task: Task) -> None:
    if (image / ".git").exists():
        fail(f"{task.id} image contains Git metadata", "harness-census qualification")
    forbidden = ("model-harness-census-v0.md", "harness-gauntlet-failure-modes.md", "reference.patch", "grader.py")
    for name, value in tree_files(image, exclude_git=True).items():
        text = value.decode("utf-8", errors="ignore")
        if any(token in text for token in forbidden):
            fail(f"{task.id} image exposes qualification material through {name}", "harness-census qualification")


def qualify_task(task: Task, source_root: Path) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix=f"harness-census-{task.id}-") as temporary:
        work = Path(temporary)
        base_a, base_b = work / "base-a", work / "base-b"
        archive_task(repo_path(source_root, task), task.source_sha, base_a)
        archive_task(repo_path(source_root, task), task.source_sha, base_b)
        fixture_digest = tree_digest(base_a, exclude_git=True)
        if fixture_digest != tree_digest(base_b, exclude_git=True):
            fail(f"{task.id} history-free image digest is not stable", "harness-census qualification")
        exposure_check(base_a, task)
        unchanged = work / "unchanged"
        shutil.copytree(base_a, unchanged, symlinks=True)
        unchanged_code, unchanged_report = run_grader(task, unchanged)
        if unchanged_code == 0 or unchanged_report.get("passed") is True:
            fail(f"{task.id} unchanged image unexpectedly passed: {unchanged_report}", "harness-census qualification")
        comment_only = work / "comment-only"
        shutil.copytree(base_a, comment_only, symlinks=True)
        with (comment_only / task.allowed_paths[0]).open("a", encoding="utf-8") as stream:
            stream.write("\n// harness-census comment-only invalid candidate\n")
        comment_code, comment_report = run_grader(task, comment_only)
        if comment_code == 0 or comment_report.get("passed") is True:
            fail(f"{task.id} comment-only candidate unexpectedly passed: {comment_report}", "harness-census qualification")
        invalid_syntax = work / "invalid-syntax"
        shutil.copytree(base_a, invalid_syntax, symlinks=True)
        with (invalid_syntax / task.allowed_paths[0]).open("a", encoding="utf-8") as stream:
            stream.write("\n<<< harness-census invalid syntax >>>\n")
        invalid_code, invalid_report = run_grader(task, invalid_syntax)
        if invalid_code == 0 or invalid_report.get("passed") is True:
            fail(f"{task.id} invalid syntax candidate unexpectedly passed: {invalid_report}", "harness-census qualification")
        reference = work / "reference"
        shutil.copytree(base_a, reference, symlinks=True)
        apply_patch(reference, task.task_dir / "reference.patch")
        changed = scope_changed(base_a, reference, task.allowed_paths)
        reference_code, reference_report = run_grader(task, reference)
        infrastructure = infrastructure_failure(reference_report)
        if infrastructure is not None:
            fail(f"{task.id} reference grader {infrastructure} failure: {reference_report}", "harness-census qualification")
        if reference_code != 0 or reference_report.get("passed") is not True:
            fail(f"{task.id} reference failed: {reference_report}", "harness-census qualification")
        reference_commit = work / "reference-commit"
        archive_task(repo_path(source_root, task), task.reference_sha, reference_commit)
        mismatched = [
            path
            for path in task.allowed_paths
            if (reference / path).read_bytes() != (reference_commit / path).read_bytes()
        ]
        if mismatched:
            fail(f"{task.id} reference patch does not reproduce reference_sha paths: {mismatched}", "harness-census qualification")
        alternatives: list[dict[str, object]] = []
        for patch in sorted((task.task_dir / "alternatives").glob("*.patch")):
            alternative = work / f"alternative-{patch.stem}"
            shutil.copytree(reference, alternative, symlinks=True)
            apply_patch(alternative, patch)
            alternative_changed = scope_changed(base_a, alternative, task.allowed_paths)
            code, report = run_grader(task, alternative)
            infrastructure = infrastructure_failure(report)
            if infrastructure is not None:
                fail(f"{task.id} equivalent alternative grader {infrastructure} failure: {report}", "harness-census qualification")
            if code != 0 or report.get("passed") is not True:
                fail(f"{task.id} equivalent alternative failed: {report}", "harness-census qualification")
            alternatives.append({"id": patch.stem, "patch_digest": file_digest(patch), "changed_paths": alternative_changed})
        if not alternatives:
            fail(f"{task.id} has no equivalent alternative fixture", "harness-census qualification")
        mutant_manifest = json.loads((task.task_dir / "mutants" / "manifest.json").read_text(encoding="utf-8"))
        mutants: list[dict[str, object]] = []
        for declaration in mutant_manifest["mutants"]:
            mutant = work / f"mutant-{declaration['id']}"
            shutil.copytree(base_a, mutant, symlinks=True)
            patch = task.task_dir / "mutants" / declaration["path"]
            apply_patch(mutant, patch)
            mutant_changed = scope_changed(base_a, mutant, task.allowed_paths)
            code, report = run_grader(task, mutant)
            marker = declaration["failure_marker"]
            infrastructure = infrastructure_failure(report)
            if infrastructure is not None:
                fail(f"{task.id} mutant {declaration['id']} grader {infrastructure} failure: {report}", "harness-census qualification")
            if code == 0 or report.get("passed") is True or report.get("failed_check") != marker:
                fail(f"{task.id} mutant {declaration['id']} did not enforce marker {marker!r}: {report}", "harness-census qualification")
            mutants.append({"id": declaration["id"], "patch_digest": file_digest(patch), "changed_paths": mutant_changed, "failure_check": report.get("failed_check")})
        receipt = {
            "schema_version": "harness_census.qualification_receipt.v1", "package_id": CAMPAIGN_ID, "task_id": task.id,
            "source_repository": task.source_repository, "source_sha": task.source_sha, "reference_sha": task.reference_sha,
            "source_cluster": task.source_cluster, "fixture": {"history_free": True, "tree_digest": fixture_digest, "stable_repeated_digest": True, "git_history_in_image": False},
            "reference": {"patch_digest": file_digest(task.task_dir / "reference.patch"), "grader_digest": file_digest(task.task_dir / "grader.py"), "reference_commit_verified": True, "passed": True, "changed_paths": changed},
            "alternatives": alternatives, "unchanged_image": {"passed": False, "intended_failure": unchanged_report["failed_check"]},
            "comment_only_image": {"passed": False, "intended_failure": comment_report.get("failed_check")}, "invalid_syntax_image": {"passed": False, "intended_failure": invalid_report.get("failed_check")},
            "mutants": mutants, "scope": {"allowed_paths": list(task.allowed_paths), "changed_paths": changed, "passed": True},
            "exposure": {"private_source_bytes_checked_in": True, "future_git_objects_exposed": False, "grader_and_reference_hidden_from_worker": True},
            "qualified": True,
        }
    receipt_path = PACKAGE / "receipts" / f"{task.id}.json"
    write_json(receipt_path, receipt)
    print(json.dumps(receipt, sort_keys=True))
    return receipt


def composition_pack() -> dict[str, dict[str, str]]:
    manifest_path = PACKAGE / "compositions" / "digests.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "harness_census.compositions.v1":
        fail("composition manifest schema is invalid", "harness-census qualification")
    result: dict[str, dict[str, str]] = {}
    for name in COMPOSITIONS:
        declaration = manifest.get(name)
        if not isinstance(declaration, dict):
            fail(f"composition declaration is missing: {name}", "harness-census qualification")
        if name == "controlled_enriched" and declaration.get("kind") == "generated_context_pack":
            result[name] = {key: str(value) for key, value in declaration.items()}
            continue
        path = PACKAGE / "compositions" / declaration["path"]
        if not path.is_file() or file_digest(path) != declaration.get("sha256"):
            fail(f"composition digest mismatch: {name}", "harness-census qualification")
        result[name] = {"path": declaration["path"], "sha256": declaration["sha256"]}
    return result


def write_smoke(receipts: list[dict[str, object]]) -> None:
    pack = composition_pack()
    receipts_by_task = {str(receipt["task_id"]): receipt for receipt in receipts}
    task_digest = digest([
        task_identity(
            task,
            str(receipts_by_task[task.id]["fixture"]["tree_digest"]),
            file_digest(task.task_dir / "instruction.md"),
            file_digest(task.task_dir / "task.toml"),
            file_digest(task.task_dir / "grader.py"),
            file_digest(task.task_dir / "reference.patch"),
        )
        for task in TASKS.values()
    ])
    gateway = gateway_identity()
    stage = {
        "schema_version": "harness_census.stage_manifest.v1", "campaign_id": CAMPAIGN_ID, "stage_id": "smoke", "bench_commit": None, "crucible_commit": None,
        "roster_digest": model_roster_digest(), "catalog_digest": harness_catalog_digest(), "harness_digest": harness_catalog_digest(), "adapter_digest": digest([entry["adapter"] for entry in qualification_harness_records()]), "pack_digest": digest(pack), "crucible_binary_digest": None, "prime_package_digest": None,
        "dockerfile_digests": [], "gateway_digests": [gateway["gateway_digest"]], "gateway_dockerfile_digests": [gateway["gateway_dockerfile_digest"]], "compose_digests": [gateway["compose_digest"]], "package_digests": [], "profile_digest": digest({"mint_base_url": MINT_INTERNAL_BASE_URL, "gateway_digests": [gateway["gateway_digest"]], "gateway_dockerfile_digests": [gateway["gateway_dockerfile_digest"]], "compose_digests": [gateway["compose_digest"]]}),
        "mcp_digest": digest({"identity": "none", "tools": [], "network": "denied"}), "task_digest": task_digest, "grader_digest": digest([receipt["reference"]["grader_digest"] for receipt in receipts]),
        "transport_network_mode": {"controlled": NETWORK_POLICY["controlled"]["transport_network_mode"], "native_default": NETWORK_POLICY["native_default"]["transport_network_mode"]},
        "network_enforcement": {"controlled": NETWORK_POLICY["controlled"]["network_enforcement"], "native_default": NETWORK_POLICY["native_default"]["network_enforcement"]},
        "task_network_enforcement": {"controlled": NETWORK_POLICY["controlled"]["task_network_enforcement"], "native_default": NETWORK_POLICY["native_default"]["task_network_enforcement"]},
        "retry_policy": {"product_retry": 0, "transport_retry": 0}, "decision_policy": {"hard_pass_requires_all_tasks": True, "native_default_separate": True},
    }
    validate_stage_manifest(stage, stage_id="smoke")
    write_json(PACKAGE / "smoke" / "stage-manifest.json", stage)
    write_json(PACKAGE / "smoke" / "harness-census-v0.json", {
        "schema_version": "crucible.eval_spec.v1", "id": "harness-census-v0-smoke", "task": CAMPAIGN_ID,
        "inputs": "Three history-free pinned repository repair tasks with deterministic graders.", "outputs": "Nine-cell dry-run staging and task receipt plumbing.",
        "graders": {"graders": [{"id": "harness_census_deterministic", "kind": "deterministic"}]}, "aggregation": "proportion", "uncertainty": {"method": "wilson", "confidence": 0.95},
        "decision": "Qualify harness identity and task receipt plumbing without paid model quality claims.", "runner": {"kind": "harbor_task", "corpus": {"source": "harbor_tasks", "config": {"agent": "pi", "agent_import_path": "crucible.harbor_agents.pi_agent:PiAgent", "model": "openrouter/deepseek/deepseek-v4-flash-0731", "job_timeout_ms": 900000, "agent_kwargs": {"mint_base_url": MINT_INTERNAL_BASE_URL}}, "tasks": [{"task_id": task.id} for task in TASKS.values()]}},
        "smoke_cells": [{**row, "task_ids": list(TASKS)} for row in campaign_matrix()],
    })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True, help="directory containing the pinned source repositories")
    parser.add_argument("--no-smoke", action="store_true", help="qualify tasks without writing smoke manifests")
    args = parser.parse_args()
    source_root = args.source_root.expanduser().resolve()
    if not source_root.is_dir():
        fail(f"source root is missing: {source_root}", "harness-census qualification")
    receipts = [qualify_task(task, source_root) for task in TASKS.values()]
    if not args.no_smoke:
        write_smoke(receipts)
    print(json.dumps({"package_id": CAMPAIGN_ID, "qualified_tasks": [receipt["task_id"] for receipt in receipts], "paid_models_called": False, "smoke_written": not args.no_smoke}, sort_keys=True))


if __name__ == "__main__":
    main()
