#!/usr/bin/env python3
"""Stage and run the nine-cell harness census through pinned Crucible."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess

from harness_census_common import (
    CAMPAIGN_ID, CONTROLLED_MODEL, HARBOR_VERSION, BUN_VERSION,
    HARNESSES, cell_summary, digest, fail, runtime_harness_records, verified_commit, write_json,
)
from harness_census_exchange import run_cell
from harness_census_staging import (
    build_cells, crucible_identity, load_compositions, probe_controlled_argv_surfaces,
    probe_harbor_task_validity, probe_verifier, qualification, require_dir,
    run_scope_probes, stage_prime_package, validate_smoke, write_harbor_wrapper,
)

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="stage and validate without invoking Crucible or providers")
    parser.add_argument("--max-cells", type=int, default=1, help="limit selected live cells after validating the full nine-cell matrix")
    parser.add_argument("--cell", action="append", default=[], help="select one cell id; repeat for multiple cells")
    parser.add_argument("--campaign-root", type=Path, required=True, help="empty campaign directory")
    parser.add_argument("--source-root", type=Path, required=True, help="directory containing pinned source repositories")
    parser.add_argument("--adapter-root", type=Path, required=True, help="pinned harbor_agents package or its parent")
    parser.add_argument("--prime-package-dir", type=Path, required=True, help="operator-supplied installed prime-agent@0.7.0 directory")
    parser.add_argument("--crucible", type=Path, help="supplied Crucible binary for live runs")
    parser.add_argument("--crucible-commit", help="runtime Crucible commit, when known")
    args = parser.parse_args()
    crucible: Path | None = None
    crucible_meta = {"commit": None, "binary_digest": None}
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
    root = args.campaign_root.expanduser().resolve()
    if root.exists() and any(root.iterdir()):
        fail(f"campaign root must be empty: {root}")
    root.mkdir(parents=True, exist_ok=True)
    qualification(source_root)
    assets, composition_digests = load_compositions()
    smoke = validate_smoke()
    prime_package = stage_prime_package(root, prime_source)
    cells = build_cells(root, assets, composition_digests, source_root, adapter_root, prime_package)
    write_json(root / "prime-package.json", {key: prime_package[key] for key in ("package", "version", "source_kind", "digest")})
    harbor = write_harbor_wrapper(root)
    commit_result = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True, capture_output=True, check=False)
    if commit_result.returncode:
        fail("Bench commit identity could not be observed")
    bench_commit = verified_commit(commit_result.stdout.strip(), "Bench commit")
    dockerfile_digests = sorted({value for cell in cells for value in cell.dockerfile_digests})
    package_digests = sorted({cell.package_digest for cell in cells})
    profile_digest = digest(sorted((cell.cell_id, cell.profile_digest) for cell in cells))
    stage = {
        "schema_version": "harness_census.stage_manifest.v1", "campaign_id": CAMPAIGN_ID, "stage_id": "campaign", "bench_commit": bench_commit,
        "crucible_commit": crucible_meta["commit"], "crucible_binary_digest": crucible_meta["binary_digest"], "roster_digest": digest(sorted(HARNESSES)),
        "catalog_digest": digest(sorted(HARNESSES)), "harness_digest": digest(runtime_harness_records()), "adapter_digest": cells[0].adapter_digest,
        "pack_digest": digest({"compositions": composition_digests, "prime_package": prime_package["digest"]}), "prime_package_digest": prime_package["digest"],
        "dockerfile_digests": dockerfile_digests, "package_digests": package_digests, "profile_digest": profile_digest,
        "mcp_digest": digest({"identity": "none", "tools": [], "network": "denied"}), "task_digest": digest(sorted({record.task_digest for cell in cells for record in cell.task_records})),
        "grader_digest": digest([record.grader_digest for record in cells[0].task_records]),
        "transport_network_mode": {"controlled": cells[1].transport_network_mode, "native_default": cells[0].transport_network_mode},
        "network_enforcement": {"controlled": cells[1].network_enforcement, "native_default": cells[0].network_enforcement},
        "task_network_enforcement": {"controlled": cells[1].task_network_enforcement, "native_default": cells[0].task_network_enforcement},
        "controlled_tool_surface_probe": controlled_tool_surface_probe, "retry_policy": {"product_retry": 0, "transport_retry": 0},
        "decision_policy": {"hard_pass_requires_all_tasks": True, "native_default_separate": True, "controlled_model_identity": CONTROLLED_MODEL, "bun_version": BUN_VERSION, "harbor_version": HARBOR_VERSION},
    }
    write_json(root / "stage-manifest.json", stage)
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
    for index, cell in enumerate(selected, 1):
        print(f"cell {index}/{len(selected)} harness={cell.harness} composition={cell.composition} model={json.dumps(cell.model_requested)} effort={json.dumps(cell.effort_requested)} tasks={len(cell.task_records)}")
    write_json(root / "campaign.json", {"schema_version": "harness_census.campaign.v1", "campaign_id": CAMPAIGN_ID, "stage_manifest_digest": stage_digest, "planned_cells": 9, "planned_trials": 27, "selected_cells": len(selected), "selected_trials": sum(len(cell.task_records) for cell in selected), "smoke_digest": smoke["smoke_digest"], "scope_probes": scope_probes, "composition_digests": composition_digests, "controlled_tool_surface_probe": controlled_tool_surface_probe, "verifier_probe": probe, "harbor_task_validity": harbor_tasks, "harbor": {"version": HARBOR_VERSION, "wrapper": str(harbor.relative_to(root))}, "cells": [cell_summary(cell) for cell in cells]})
    if args.dry_run:
        print(f"dry-run cells={len(selected)} trials={sum(len(cell.task_records) for cell in selected)} provider_calls=0")
        return
    version = subprocess.run([str(harbor), "--version"], env={**os.environ, "PATH": f"{harbor.parent}:{os.environ.get('PATH', '')}"}, text=True, capture_output=True, check=False)
    observed_harbor = (version.stdout + version.stderr).strip()
    if version.returncode or HARBOR_VERSION not in observed_harbor:
        fail(f"Harbor {HARBOR_VERSION} preflight failed: {observed_harbor}")
    campaign = json.loads((root / "campaign.json").read_text(encoding="utf-8"))
    campaign["harbor"]["observed_version"] = observed_harbor
    write_json(root / "campaign.json", campaign)
    for cell in selected:
        run_cell(root, cell, crucible, harbor, stage_digest)
    print(f"run cells={len(selected)} trials={sum(len(cell.task_records) for cell in selected)} provider_calls=runtime")


if __name__ == "__main__":
    main()
