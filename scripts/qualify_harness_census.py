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
    CAMPAIGN_ID, CONTROLLED_NETWORK_ENFORCEMENT, CONTROLLED_TASK_NETWORK_ENFORCEMENT, CONTROLLED_TRANSPORT_NETWORK_MODE, DECISION_POLICY, MANIFEST, NATIVE_NETWORK_ENFORCEMENT, NATIVE_TASK_NETWORK_ENFORCEMENT, NATIVE_TRANSPORT_NETWORK_MODE, PACKAGE, RETRY_POLICY, Task, campaign_matrix,
    digest, fail, file_digest, harness_catalog_digest, load_tasks, mcp_identity_digest, model_roster_digest,
    qualification_harness_records, reference_hunk_map_digest, reference_hunk_mapping,
    task_identity, tree_digest, tree_files, write_json,
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


def score_report(report: Mapping[str, object], *, task_id: str) -> tuple[int, int, float, bool]:
    passed = report.get("passed_checks")
    total = report.get("total_checks")
    points = report.get("task_points")
    hard_pass = report.get("passed")
    if isinstance(passed, bool) or not isinstance(passed, int) or isinstance(total, bool) or not isinstance(total, int) or total <= 0 or passed < 0 or passed > total or isinstance(points, bool) or not isinstance(points, (int, float)) or points != passed / total or not isinstance(hard_pass, bool) or hard_pass != (passed == total):
        fail(f"{task_id} grader score is missing or inconsistent: {report}", "harness-census qualification")
    return passed, total, float(points), hard_pass


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
        score_report(unchanged_report, task_id=task.id)
        if unchanged_code == 0 or unchanged_report.get("passed") is True:
            fail(f"{task.id} unchanged image unexpectedly passed: {unchanged_report}", "harness-census qualification")
        comment_only = work / "comment-only"
        shutil.copytree(base_a, comment_only, symlinks=True)
        with (comment_only / task.allowed_paths[0]).open("a", encoding="utf-8") as stream:
            stream.write("\n// harness-census comment-only invalid candidate\n")
        comment_code, comment_report = run_grader(task, comment_only)
        score_report(comment_report, task_id=task.id)
        if comment_code == 0 or comment_report.get("passed") is True:
            fail(f"{task.id} comment-only candidate unexpectedly passed: {comment_report}", "harness-census qualification")
        invalid_syntax = work / "invalid-syntax"
        shutil.copytree(base_a, invalid_syntax, symlinks=True)
        with (invalid_syntax / task.allowed_paths[0]).open("a", encoding="utf-8") as stream:
            stream.write("\n<<< harness-census invalid syntax >>>\n")
        invalid_code, invalid_report = run_grader(task, invalid_syntax)
        score_report(invalid_report, task_id=task.id)
        if invalid_code == 0 or invalid_report.get("passed") is True:
            fail(f"{task.id} invalid syntax candidate unexpectedly passed: {invalid_report}", "harness-census qualification")
        reference = work / "reference"
        shutil.copytree(base_a, reference, symlinks=True)
        apply_patch(reference, task.task_dir / "reference.patch")
        changed = scope_changed(base_a, reference, task.allowed_paths)
        reference_code, reference_report = run_grader(task, reference)
        _, reference_total, reference_points, reference_hard_pass = score_report(reference_report, task_id=task.id)
        infrastructure = infrastructure_failure(reference_report)
        if infrastructure is not None:
            fail(f"{task.id} reference grader {infrastructure} failure: {reference_report}", "harness-census qualification")
        if reference_code != 0 or reference_hard_pass is not True or reference_points != 1.0:
            fail(f"{task.id} reference failed: {reference_report}", "harness-census qualification")
        reference_hunks = reference_hunk_mapping(task)
        grader_checks = reference_report.get("checks")
        if not isinstance(grader_checks, list) or any(hunk.grader_check not in grader_checks for hunk in reference_hunks):
            fail(f"{task.id} reference hunk mapping names checks absent from grader: {reference_hunks} / {grader_checks}", "harness-census qualification")
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
            alternative_passed, alternative_total, alternative_points, alternative_hard_pass = score_report(report, task_id=task.id)
            infrastructure = infrastructure_failure(report)
            if infrastructure is not None:
                fail(f"{task.id} equivalent alternative grader {infrastructure} failure: {report}", "harness-census qualification")
            if code != 0 or alternative_hard_pass is not True or alternative_points != 1.0:
                fail(f"{task.id} equivalent alternative failed: {report}", "harness-census qualification")
            alternatives.append({"id": patch.stem, "patch_digest": file_digest(patch), "changed_paths": alternative_changed, "passed_checks": alternative_passed, "total_checks": alternative_total, "task_points": alternative_points, "hard_pass": alternative_hard_pass})
        minimum_alternatives = int(MANIFEST["qualification"]["alternatives_per_task_minimum"])
        if len(alternatives) < minimum_alternatives:
            fail(f"{task.id} has {len(alternatives)} equivalent alternatives; minimum is {minimum_alternatives}", "harness-census qualification")
        mutant_manifest = json.loads((task.task_dir / "mutants" / "manifest.json").read_text(encoding="utf-8"))
        mutants: list[dict[str, object]] = []
        for declaration in mutant_manifest["mutants"]:
            mutant = work / f"mutant-{declaration['id']}"
            shutil.copytree(base_a, mutant, symlinks=True)
            patch = task.task_dir / "mutants" / declaration["path"]
            apply_patch(mutant, patch)
            mutant_changed = scope_changed(base_a, mutant, task.allowed_paths)
            code, report = run_grader(task, mutant)
            score_report(report, task_id=task.id)
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
            "reference": {"patch_digest": file_digest(task.task_dir / "reference.patch"), "grader_digest": file_digest(task.task_dir / "grader.py"), "reference_commit_verified": True, "passed": True, "hard_pass": True, "passed_checks": reference_report["passed_checks"], "total_checks": reference_total, "task_points": reference_points, "changed_paths": changed},
            "reference_hunks": [{"hunk_id": hunk.hunk_id, "header": hunk.header, "patch_digest": hunk.patch_digest, "grader_check": hunk.grader_check} for hunk in reference_hunks],
            "reference_hunk_map_digest": reference_hunk_map_digest(task),
            "alternatives": alternatives, "unchanged_image": {"passed": False, "intended_failure": unchanged_report["failed_check"]},
            "comment_only_image": {"passed": False, "intended_failure": comment_report.get("failed_check")}, "invalid_syntax_image": {"passed": False, "intended_failure": invalid_report.get("failed_check")},
            "mutants": mutants, "scope": {"allowed_paths": list(task.allowed_paths), "changed_paths": changed, "passed": True},
            "exposure": {"private_source_bytes_checked_in": False, "future_git_objects_exposed": False, "grader_and_reference_hidden_from_worker": True},
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
    task_digests = [
        task_identity(
            task,
            str(receipts_by_task[task.id]["fixture"]["tree_digest"]),
            file_digest(task.task_dir / "instruction.md"),
            file_digest(task.task_dir / "task.toml"),
            file_digest(task.task_dir / "grader.py"),
            file_digest(task.task_dir / "reference.patch"),
            reference_hunk_map_digest(task),
        )
        for task in TASKS.values()
    ]
    task_digest = digest(task_digests)
    hunk_map_digest = digest([reference_hunk_map_digest(task) for task in TASKS.values()])
    gateway = gateway_identity()
    stage = {
        "schema_version": "harness_census.stage_manifest.v1", "campaign_id": CAMPAIGN_ID, "stage_id": "smoke", "bench_commit": None, "crucible_commit": None,
        "roster_digest": model_roster_digest(), "catalog_digest": harness_catalog_digest(), "adapter_digest": digest([entry["adapter"] for entry in qualification_harness_records()]), "pack_digest": digest(pack), "crucible_binary_digest": None, "prime_package_digest": None,
        "dockerfile_digests": [], "gateway_digests": [gateway["gateway_digest"]], "gateway_dockerfile_digests": [gateway["gateway_dockerfile_digest"]], "compose_digests": [gateway["compose_digest"]], "package_digests": [], "profile_digest": digest({"mint_base_url": MINT_INTERNAL_BASE_URL, "gateway_digests": [gateway["gateway_digest"]], "gateway_dockerfile_digests": [gateway["gateway_dockerfile_digest"]], "compose_digests": [gateway["compose_digest"]]}),
        "mcp_digest": mcp_identity_digest(), "task_digest": task_digest, "reference_hunk_map_digest": hunk_map_digest, "grader_digest": digest([receipt["reference"]["grader_digest"] for receipt in receipts]),
        "transport_network_mode": {"controlled": CONTROLLED_TRANSPORT_NETWORK_MODE, "native_default": NATIVE_TRANSPORT_NETWORK_MODE},
        "network_enforcement": {"controlled": CONTROLLED_NETWORK_ENFORCEMENT, "native_default": NATIVE_NETWORK_ENFORCEMENT},
        "task_network_enforcement": {"controlled": CONTROLLED_TASK_NETWORK_ENFORCEMENT, "native_default": NATIVE_TASK_NETWORK_ENFORCEMENT},
        "retry_policy": dict(RETRY_POLICY), "decision_policy": dict(DECISION_POLICY),
    }
    validate_stage_manifest(stage, stage_id="smoke")
    write_json(PACKAGE / "smoke" / "stage-manifest.json", stage)
    smoke_cells = []
    for row in campaign_matrix():
        identity = digest({"cell": row, "task_digest": task_digest, "reference_hunk_map_digest": hunk_map_digest})
        smoke_cells.append({**row, "task_ids": list(TASKS), "identity_digest": identity})
    write_json(PACKAGE / "smoke" / "harness-census-v0.json", {
        "schema_version": "harness_census.smoke.v1", "id": "harness-census-v0-smoke", "kind": "staging_manifest", "runnable": False,
        "task_ids": list(TASKS), "task_digest": task_digest, "reference_hunk_map_digest": hunk_map_digest, "grader_digest": stage["grader_digest"], "pack_digest": stage["pack_digest"],
        "cells": smoke_cells,
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
