#!/usr/bin/env python3
"""Stage and run the nine-cell harness census through pinned Crucible."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess

from harness_census_common import (
    BUN_VERSION, CAMPAIGN_ID, CONTROLLED_MODEL, HARBOR_VERSION,
    HARNESSES, cell_summary, confined_path, digest, ensure_campaign_layout, ensure_campaign_root,
    fail, harness_catalog_digest, model_roster_digest, runtime_harness_records, verified_commit, write_json,
)
from harness_census_exchange import run_cell, safe_runtime_environment
from harness_census_staging import (
    build_cells, cell_receipt_state, crucible_identity, ensure_clean_bench_source, immutable_stage_cells, load_compositions, pending_task_ids, preflight_worker_images,
    probe_controlled_argv_surfaces, probe_harbor_task_validity, probe_verifier, qualification, require_dir,
    resume_staged_cells, run_scope_probes, stage_prime_package, staged_bytes_digest, validate_smoke, validate_stage_manifest, write_harbor_wrapper,
)

ROOT = Path(__file__).resolve().parents[1]


def campaign_stage(cells: tuple, composition_digests: dict[str, str], prime_package: dict[str, str], crucible_meta: dict[str, str | None], bench_commit: str, controlled_probe: dict[str, object], worker_preflight_digest: str) -> dict[str, object]:
    dockerfile_digests = sorted({value for cell in cells for value in cell.dockerfile_digests})
    gateway_digests = sorted({value for cell in cells for value in cell.gateway_digests})
    gateway_dockerfile_digests = sorted({value for cell in cells for value in cell.gateway_dockerfile_digests})
    compose_digests = sorted({value for cell in cells for value in cell.compose_digests})
    package_digests = sorted({cell.package_digest for cell in cells})
    reference_hunk_map_digest = digest(sorted((record.task_id, record.reference_hunk_map_digest) for cell in cells for record in cell.task_records))
    return {
        "schema_version": "harness_census.stage_manifest.v1", "campaign_id": CAMPAIGN_ID, "stage_id": "campaign", "bench_commit": bench_commit,
        "crucible_commit": crucible_meta["commit"], "crucible_binary_digest": crucible_meta["binary_digest"], "roster_digest": model_roster_digest(),
        "catalog_digest": harness_catalog_digest(), "harness_digest": harness_catalog_digest(), "adapter_digest": cells[0].adapter_digest,
        "pack_digest": digest({"compositions": composition_digests, "context": sorted((cell.cell_id, record.task_id, record.context_manifest_digest, record.context_pack_digest, record.context_digest, record.skill_digest) for cell in cells for record in cell.task_records), "gateway_digests": gateway_digests, "gateway_dockerfile_digests": gateway_dockerfile_digests, "compose_digests": compose_digests, "prime_package": prime_package["digest"]}), "prime_package_digest": prime_package["digest"],
        "dockerfile_digests": dockerfile_digests, "gateway_digests": gateway_digests, "gateway_dockerfile_digests": gateway_dockerfile_digests, "compose_digests": compose_digests, "package_digests": package_digests, "profile_digest": digest(sorted((cell.cell_id, cell.profile_digest) for cell in cells)),
        "mcp_digest": digest({"identity": "none", "tools": [], "network": "denied"}), "task_digest": digest(sorted({record.task_digest for cell in cells for record in cell.task_records})), "reference_hunk_map_digest": reference_hunk_map_digest,
        "grader_digest": digest([record.grader_digest for record in cells[0].task_records]),
        "transport_network_mode": {"controlled": cells[1].transport_network_mode, "native_default": cells[0].transport_network_mode},
        "network_enforcement": {"controlled": cells[1].network_enforcement, "native_default": cells[0].network_enforcement},
        "task_network_enforcement": {"controlled": cells[1].task_network_enforcement, "native_default": cells[0].task_network_enforcement},
        "controlled_tool_surface_probe": controlled_probe, "retry_policy": {"product_retry": 0, "transport_retry": 0},
        "decision_policy": {"decision": "scale_or_repair", "task_buckets": 3, "paired_delta_resolvable": {"point_delta": 1.0}, "interval_claims": {"descriptive": True, "inferential": False}, "forbidden_claims": ["winner", "deployment", "context_deletion"], "cell_invalidation": "any_reliability_failure", "hard_pass_requires_all_tasks": True, "native_default_separate": True, "controlled_model_identity": CONTROLLED_MODEL, "bun_version": BUN_VERSION, "harbor_version": HARBOR_VERSION},
        "cells": immutable_stage_cells(cells), "worker_preflight_digest": worker_preflight_digest,
    }


def bench_commit() -> str:
    result = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True, capture_output=True, check=False)
    if result.returncode:
        fail("Bench commit identity could not be observed")
    return verified_commit(result.stdout.strip(), "Bench commit")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="stage and validate without invoking Crucible or providers")
    parser.add_argument("--resume", action="store_true", help="resume a non-empty frozen campaign root after identity checks")
    parser.add_argument("--max-cells", type=int, default=1, help="limit selected live cells after validating the full nine-cell matrix")
    parser.add_argument("--cell", action="append", default=[], help="select one cell id; repeat for multiple cells")
    parser.add_argument("--campaign-root", type=Path, required=True, help="empty campaign directory, or existing staged root with --resume")
    parser.add_argument("--source-root", type=Path, required=True, help="directory containing pinned source repositories")
    parser.add_argument("--adapter-root", type=Path, required=True, help="pinned harbor_agents package or its parent")
    parser.add_argument("--prime-package-dir", type=Path, required=True, help="operator-supplied installed prime-agent@0.7.0 directory")
    parser.add_argument("--crucible", type=Path, help="supplied Crucible binary for live runs")
    parser.add_argument("--crucible-commit", help="runtime Crucible commit, when known")
    args = parser.parse_args()
    crucible: Path | None = None
    crucible_meta: dict[str, str | None] = {"commit": None, "binary_digest": None}
    if args.crucible is not None:
        crucible = args.crucible.expanduser().resolve()
        if not crucible.is_file():
            fail(f"Crucible binary is missing: {crucible}")
        crucible_meta = crucible_identity(crucible)
        if args.crucible_commit is not None and verified_commit(args.crucible_commit, "Crucible commit claim") != crucible_meta["commit"]:
            fail("Crucible commit claim does not match the observed binary identity")
    elif args.crucible_commit is not None:
        fail("Crucible commit claims require an observed --crucible binary")
    if not args.dry_run and crucible is None:
        fail("live runs require --crucible")
    if not 1 <= args.max_cells <= 9:
        fail("--max-cells must be between 1 and 9")
    source_root = require_dir(args.source_root, "source root")
    adapter_root = require_dir(args.adapter_root, "adapter root")
    prime_source = require_dir(args.prime_package_dir, "Prime package directory")
    controlled_tool_surface_probe = probe_controlled_argv_surfaces(adapter_root)
    raw_root = args.campaign_root.expanduser()
    home = Path.home().resolve()
    if not raw_root.is_relative_to(home):
        fail(f"campaign root must be under $HOME ({home}) for Harbor Docker mounts: {raw_root}")
    if args.resume:
        reserve = ensure_campaign_root(raw_root)
        if not reserve.is_dir() or not any(reserve.iterdir()):
            fail(f"--resume requires a non-empty staged campaign root: {reserve}")
    elif raw_root.exists() and any(raw_root.iterdir()):
        fail(f"campaign root must be empty: {raw_root}")
    root = ensure_campaign_root(raw_root)
    ensure_clean_bench_source()
    current_bench_commit = bench_commit()
    harbor = confined_path(root, "bin", "harbor")
    expected_cell_digests: dict[str, str] = {}
    if args.resume:
        ensure_campaign_layout(root)
        stage_path, campaign_path = confined_path(root, "stage-manifest.json"), confined_path(root, "campaign.json")
        if not stage_path.is_file() or not campaign_path.is_file():
            fail("--resume requires stage-manifest.json and campaign.json")
        try:
            stage = json.loads(stage_path.read_text(encoding="utf-8"))
            campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            fail(f"--resume metadata is invalid JSON: {error}")
        validate_stage_manifest(stage, stage_id="campaign")
        stage_digest = digest(stage)
        if campaign.get("stage_manifest_digest") != stage_digest or campaign.get("campaign_id") != CAMPAIGN_ID:
            fail("--resume campaign metadata does not bind to stage-manifest.json")
        if stage.get("bench_commit") != current_bench_commit or stage.get("crucible_commit") != crucible_meta["commit"] or stage.get("crucible_binary_digest") != crucible_meta["binary_digest"]:
            fail("--resume runtime identity differs from the frozen stage")
        worker_preflight = campaign.get("worker_preflight")
        if not isinstance(worker_preflight, dict) or worker_preflight.get("status") != "passed" or worker_preflight.get("checks") != 9:
            fail("--resume requires nine passed in-image worker preflight checks")
        try:
            worker_report = json.loads(confined_path(root, "worker-preflight.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as error:
            fail(f"--resume worker preflight artifact is invalid: {error}")
        if worker_report != worker_preflight or stage.get("worker_preflight_digest") != digest(worker_report):
            fail("--resume worker preflight metadata differs from the immutable stage")
        cells, composition_digests, prime_package, expected_cell_digests = resume_staged_cells(root, source_root, adapter_root, prime_source)
        expected_stage = campaign_stage(cells, composition_digests, prime_package, crucible_meta, current_bench_commit, controlled_tool_surface_probe, digest(worker_report))
        if stage != expected_stage:
            fail("--resume stage manifest identity differs from current Bench inputs")
        expected_prime = {key: prime_package[key] for key in ("package", "version", "source_kind", "digest")}
        try:
            if json.loads(confined_path(root, "prime-package.json").read_text(encoding="utf-8")) != expected_prime:
                fail("--resume Prime package metadata differs from the frozen stage")
        except (FileNotFoundError, json.JSONDecodeError) as error:
            fail(f"--resume Prime package metadata is invalid: {error}")
        expected_summaries = [cell_summary(cell) for cell in cells]
        if campaign.get("schema_version") != "harness_census.campaign.v1" or campaign.get("cells") != expected_summaries or campaign.get("planned_cells") != 9 or campaign.get("planned_trials") != 27 or campaign.get("composition_digests") != composition_digests:
            fail("--resume campaign cell or task-set metadata differs from the frozen stage")
        harbor_metadata = campaign.get("harbor")
        if not isinstance(harbor_metadata, dict) or harbor_metadata.get("version") != HARBOR_VERSION or harbor_metadata.get("wrapper") != "bin/harbor":
            fail("--resume Harbor metadata is invalid")
        if campaign.get("immutable_stage_digest") != staged_bytes_digest(root):
            fail("--resume immutable stage digest does not match staged bytes")
        selected_ids = campaign.get("selected_cell_ids")
        run_kind = campaign.get("run_kind")
        if not isinstance(selected_ids, list) or set(selected_ids) - {cell.cell_id for cell in cells} or run_kind not in {"final", "partial"}:
            fail("--resume campaign selection metadata is invalid")
        states = {cell.cell_id: cell_receipt_state(root, cell, stage_digest, expected_cell_digests[cell.cell_id]) for cell in cells}
        stored_status = campaign.get("cell_status")
        if not isinstance(stored_status, dict) or set(stored_status) != {cell.cell_id for cell in cells} or campaign.get("completion_status") not in {"staged", "partial", "complete", "invalid"}:
            fail("--resume campaign terminal metadata is invalid")
        for cell_id, state in states.items():
            if stored_status[cell_id] in {"complete", "invalid"} and stored_status[cell_id] != state:
                fail(f"--resume campaign terminal state disagrees with receipts: {cell_id}")
        if campaign.get("completion_status") == "complete" and any(state != "complete" for state in states.values()):
            fail("--resume campaign claims complete without 27 quality receipts")
        if campaign.get("completion_status") == "invalid" and "invalid" not in states.values():
            fail("--resume campaign claims invalid without a reliability receipt")
        selected = [cell for cell in cells if cell.cell_id in selected_ids]
        if args.cell:
            unknown = sorted(set(args.cell) - {cell.cell_id for cell in selected})
            if unknown:
                fail(f"unknown --cell selection for resume: {', '.join(unknown)}")
            selected = [cell for cell in selected if cell.cell_id in args.cell]
        selected = [cell for cell in selected if states[cell.cell_id] not in {"complete", "invalid"}]
    else:
        qualification(source_root)
        assets, composition_digests = load_compositions()
        smoke = validate_smoke()
        prime_package = stage_prime_package(root, prime_source)
        cells = build_cells(root, assets, composition_digests, source_root, adapter_root, prime_package)
        write_json(confined_path(root, "prime-package.json"), {key: prime_package[key] for key in ("package", "version", "source_kind", "digest")})
        harbor = write_harbor_wrapper(root)
        ensure_clean_bench_source()
        worker_preflight = preflight_worker_images(root, cells)
        worker_preflight_digest = digest(worker_preflight)
        stage = campaign_stage(cells, composition_digests, prime_package, crucible_meta, current_bench_commit, controlled_tool_surface_probe, worker_preflight_digest)
        validate_stage_manifest(stage, stage_id="campaign")
        write_json(confined_path(root, "stage-manifest.json"), stage)
        stage_digest = digest(stage)
        probe = probe_verifier(root, cells[0])
        scope_probes = run_scope_probes(root, cells[0])
        harbor_tasks = probe_harbor_task_validity(cells)
        selected = list(cells)
        if args.cell:
            unknown = sorted(set(args.cell) - {cell.cell_id for cell in cells})
            if unknown:
                fail(f"unknown --cell selection: {', '.join(unknown)}")
            selected = [cell for cell in cells if cell.cell_id in args.cell]
        if args.cell and len(selected) > args.max_cells:
            fail(f"selected {len(selected)} cells exceeds --max-cells {args.max_cells}")
        if not args.dry_run and not args.cell:
            fail("live runs require at least one explicit --cell")
        run_kind = "final" if len(selected) == len(cells) == 9 else "partial"
        campaign = {"schema_version": "harness_census.campaign.v1", "campaign_id": CAMPAIGN_ID, "stage_manifest_digest": stage_digest, "planned_cells": 9, "planned_trials": 27, "selected_cells": len(selected), "selected_trials": sum(len(cell.task_records) for cell in selected), "selected_cell_ids": [cell.cell_id for cell in selected], "run_kind": run_kind, "completion_status": "staged", "cell_status": {cell.cell_id: "staged" for cell in cells}, "immutable_stage_digest": staged_bytes_digest(root), "smoke_digest": smoke["smoke_digest"], "worker_preflight": worker_preflight, "scope_probes": scope_probes, "composition_digests": composition_digests, "controlled_tool_surface_probe": controlled_tool_surface_probe, "verifier_probe": probe, "harbor_task_validity": harbor_tasks, "harbor": {"version": HARBOR_VERSION, "wrapper": str(harbor.relative_to(root))}, "cells": [cell_summary(cell) for cell in cells]}
        write_json(confined_path(root, "campaign.json"), campaign)
        expected_cell_digests = {cell.cell_id: cell_stage_digest(cell.cell_dir, include_workspace=False) for cell in cells}
    for index, cell in enumerate(selected, 1):
        print(f"cell {index}/{len(selected)} harness={cell.harness} composition={cell.composition} model={json.dumps(cell.model_requested)} effort={json.dumps(cell.effort_requested)} tasks={len(cell.task_records)}")
    if args.dry_run:
        print(f"dry-run cells={len(selected)} trials={sum(len(cell.task_records) for cell in selected)} provider_calls=0")
        return
    if not harbor.is_file():
        fail(f"staged Harbor wrapper is missing: {harbor}")
    version = subprocess.run([str(harbor), "--version"], env=safe_runtime_environment(harbor), text=True, capture_output=True, check=False)
    observed_harbor = (version.stdout + version.stderr).strip()
    if version.returncode or HARBOR_VERSION not in observed_harbor:
        fail(f"Harbor {HARBOR_VERSION} preflight failed: {observed_harbor}")
    if not args.resume:
        campaign["harbor"]["observed_version"] = observed_harbor
        write_json(confined_path(root, "campaign.json"), campaign)
    for cell in selected:
        pending = pending_task_ids(root, cell)
        run_cell(root, cell, crucible, harbor, stage_digest, expected_cell_digests[cell.cell_id], task_ids=pending or None)
    terminal_states = {cell.cell_id: cell_receipt_state(root, cell, stage_digest, expected_cell_digests[cell.cell_id]) for cell in cells}
    if run_kind == "final" and not args.resume:
        if any(state not in {"complete", "invalid"} for state in terminal_states.values()):
            fail("final campaign stopped before all 27 canonical receipts became terminal")
    campaign["cell_status"] = terminal_states
    if any(state == "invalid" for state in terminal_states.values()):
        campaign["completion_status"] = "invalid"
    elif all(state in {"complete", "invalid"} for state in terminal_states.values()):
        campaign["completion_status"] = "complete"
    else:
        campaign["completion_status"] = "partial"
    if run_kind == "final" and not args.resume:
        campaign["persisted_trials"] = 27
    write_json(confined_path(root, "campaign.json"), campaign)
    print(f"run cells={len(selected)} trials={sum(len(cell.task_records) for cell in selected)} provider_calls=runtime")


if __name__ == "__main__":
    main()
