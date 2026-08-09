from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from harness_census_common import (
    CAMPAIGN_ID,
    CONTROLLED_EFFORT,
    CONTROLLED_MODEL,
    Cell,
    TaskRecord,
    agent_allowed_hosts_identity_digest,
    agent_kwargs_identity_digest,
    bytes_digest,
    campaign_tree_files,
    canonical,
    cell_stage_digest,
    digest,
    harbor_reward_value,
    load_tasks,
    mcp_identity_digest,
    worker_image_tag,
)

from harness_census_gateway import compose_yaml, write_gateway_assets
from harness_census_exchange import collect_attestations, exchange_envelopes, native_observation, run_cell
from harness_census_generation import _prime_payload, dockerfile, node_toolchain_package_info, prime_package_info, runtime_package_info, stage_prime_package, verifier_source
from harness_census_staging import staged_task_toml
from harness_census_resume import _derive_cell_result, _reconcile_native_baseline, cell_receipt_state, pending_task_ids, receipt_task_ids, staged_bytes_digest, verify_pending_task_sources




from harness_census_test_support import (
    TASK_IDS,
    build_complete,
    content_ref,
    install_reliability_receipt,
    h64,
    make_cell,
    make_prime_package,
    stage_task_artifacts,
    write_db,
)


class HarnessCensusResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="census-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cell = make_cell(self.root)
        self.stage_digest = h64(0xFF)

    def test_resume_rejects_changed_controlled_pair_before_receipts(self) -> None:
        from dataclasses import replace

        build_complete(self.root, self.cell, self.stage_digest)
        mismatched = replace(
            self.cell,
            model_requested="openrouter/deepseek/deepseek-v4-flash-0731",
            effort_requested="high",
            provider_route_resolved="openrouter/deepseek/deepseek-v4-flash-0731",
            provider_effort_resolved="high",
        )
        with self.assertRaisesRegex(SystemExit, "resume receipt cell identity mismatch"):
            cell_receipt_state(self.root, mismatched, self.stage_digest)
    def test_runtime_package_changes_stage_digests_but_mutable_state_does_not(self) -> None:
        runtime = self.cell.cell_dir / "tasks" / TASK_IDS[0] / "environment" / "runtime-package"
        repo = self.cell.cell_dir / "tasks" / TASK_IDS[0] / "environment" / "repo"
        results = self.cell.cell_dir / "results"
        runs = self.cell.cell_dir / "runs"
        for directory in (runtime, repo, results, runs):
            directory.mkdir(parents=True)
        runtime_file, repo_file = runtime / "package.tgz", repo / "source.txt"
        results_file, runs_file = results / "result.json", runs / "run.json"
        runtime_file.write_bytes(b"runtime-v1")
        repo_file.write_bytes(b"repo-v1")
        results_file.write_bytes(b"results-v1")
        runs_file.write_bytes(b"runs-v1")
        cell_before = cell_stage_digest(self.cell.cell_dir, include_workspace=False)
        staged_before = staged_bytes_digest(self.root)
        runtime_file.write_bytes(b"runtime-v2")
        self.assertNotEqual(cell_stage_digest(self.cell.cell_dir, include_workspace=False), cell_before)
        self.assertNotEqual(staged_bytes_digest(self.root), staged_before)
        cell_after_runtime = cell_stage_digest(self.cell.cell_dir, include_workspace=False)
        staged_after_runtime = staged_bytes_digest(self.root)
        for path, value in ((repo_file, b"repo-v2"), (results_file, b"results-v2"), (runs_file, b"runs-v2")):
            path.write_bytes(value)
            self.assertEqual(cell_stage_digest(self.cell.cell_dir, include_workspace=False), cell_after_runtime)
            self.assertEqual(staged_bytes_digest(self.root), staged_after_runtime)


    def test_absent_cell_selects_all_tasks(self) -> None:
        self.assertEqual(cell_receipt_state(self.root, self.cell, self.stage_digest), "absent")
        self.assertEqual(pending_task_ids(self.root, self.cell), TASK_IDS)

    def test_one_valid_receipt_is_partial_with_two_pending_tasks(self) -> None:
        receipt: dict[str, object] = {}
        stage_task_artifacts(self.root, self.cell, self.stage_digest, self.cell.task_records[0], receipt)
        write_db(self.root, [receipt])
        self.assertEqual(cell_receipt_state(self.root, self.cell, self.stage_digest), "partial")
        self.assertEqual(pending_task_ids(self.root, self.cell), TASK_IDS[1:])

    def test_task_canary_does_not_materialize_unselected_failures(self) -> None:
        results = self.cell.cell_dir / "results"
        selected = collect_attestations(results, self.cell, [self.cell.task_records[0]])
        self.assertEqual([entry["task_id"] for entry in selected], [TASK_IDS[0]])
        for task_id in TASK_IDS[1:]:
            self.assertFalse((results / "harbor-jobs" / task_id).exists())
        self.assertEqual(collect_attestations(results, self.cell, materialize_missing=False), selected)

    def test_exchange_envelopes_write_provider_failure_receipt(self) -> None:
        from dataclasses import replace

        instruction = b"repair the task\n"
        context_manifest: dict[str, object] = {}
        context_pack = b"context\n"
        record = replace(
            self.cell.task_records[0],
            context_digest=bytes_digest(instruction),
            context_manifest_digest=digest(context_manifest),
            context_pack_digest=bytes_digest(context_pack),
        )
        cell = replace(self.cell, task_records=(record, *self.cell.task_records[1:]))
        task_dir = cell.cell_dir / record.task_dir
        (task_dir / "tests").mkdir(parents=True)
        (task_dir / "instruction.md").write_bytes(instruction)
        (task_dir / "tests" / "verify.py").write_text("pass\n", encoding="utf-8")
        manifest_path = self.root / "context" / "manifests" / f"{record.context_manifest_digest}.json"
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text(json.dumps(context_manifest), encoding="utf-8")
        pack_path = self.root / "context" / "packs" / f"{record.context_pack_digest}.md"
        pack_path.parent.mkdir(parents=True)
        pack_path.write_bytes(context_pack)
        trial_dir = cell.cell_dir / "results" / "harbor-jobs" / record.task_id / "run" / "trial"
        trial_dir.mkdir(parents=True)
        (trial_dir / "result.json").write_text(
            json.dumps({"task_name": record.task_id, "started_at": "2026-08-09T00:00:00Z", "finished_at": "2026-08-09T00:00:01Z", "exception_info": {"exception_type": "ProviderError", "exception_message": "blocked"}}),
            encoding="utf-8",
        )
        attestation = {
            "schema_version": "crucible.adapter_attestation.v1",
            "adapter": cell.harness,
            "composition": cell.composition,
            "version": cell.harness_version,
            "status": "failed",
            "observed_identities": [],
            "reason": "provider_error",
        }
        attestation_path = trial_dir / "omp.attestation.json"
        attestation_path.write_text(json.dumps(attestation), encoding="utf-8")
        entry = {
            "task_id": record.task_id,
            "trial_dir": trial_dir,
            "attestation_path": attestation_path,
            "attestation_ref": attestation_path.relative_to(cell.cell_dir).as_posix(),
            "attestation_digest": bytes_digest(attestation_path.read_bytes()),
            "transcript_ref": None,
            "transcript_path": None,
            "record": attestation,
        }

        paths = exchange_envelopes(self.root, cell, record, trial_dir, entry, self.stage_digest, None, ("2026-08-09T00:00:00Z", "2026-08-09T00:00:01Z"))
        trial = json.loads(paths.trial.read_text(encoding="utf-8"))
        result = json.loads(paths.result.read_text(encoding="utf-8"))
        self.assertEqual(trial["source_cluster"], record.source_cluster)
        self.assertEqual(trial["trial_status"], "reliability_failure")
        self.assertEqual(trial["failure_code"], "provider_request_failed")
        self.assertEqual(result["status"], "execution_error")
        self.assertTrue(result["error"]["retryable"])
        self.assertIsNone(paths.grader)
        (trial_dir / "result.json").write_text(json.dumps({"task_name": record.task_id}), encoding="utf-8")
        malformed = exchange_envelopes(self.root, cell, record, trial_dir, entry, self.stage_digest, None, ("2026-08-09T00:00:00Z", "2026-08-09T00:00:01Z"))
        malformed_trial = json.loads(malformed.trial.read_text(encoding="utf-8"))
        self.assertEqual(malformed_trial["failure_code"], "harbor_trial_malformed")
        self.assertEqual(malformed_trial["failure_detail"]["timestamp_fallback_source"], "bench_cell_subprocess_bounds")

    def test_three_valid_receipts_are_complete(self) -> None:
        build_complete(self.root, self.cell, self.stage_digest)
        self.assertEqual(cell_receipt_state(self.root, self.cell, self.stage_digest), "complete")
        self.assertEqual(pending_task_ids(self.root, self.cell), [])

    def test_native_baseline_reconciles_all_canonical_receipts(self) -> None:
        from dataclasses import replace

        cell = replace(self.cell, cell_kind="native_default", composition="native_default", model_requested=None, effort_requested=None, provider_route_resolved=None, provider_effort_resolved=None, row_id=None, cohort_id=None, baseline_id=None)
        resolved = cell.resolve_native(CONTROLLED_MODEL, "high", "requested", h64(0xF1), h64(0xF2))
        by_task = {
            record.task_id: ({"task_id": record.task_id, "task_name": record.task_id, "trial_status": "success", "receipt_id": f"receipt-{index}"}, 1)
            for index, record in enumerate(cell.task_records, 1)
        }
        observation = {"model": CONTROLLED_MODEL, "effort": "high", "effort_source": "requested", "tool": h64(0xF1), "config": h64(0xF2)}
        _reconcile_native_baseline(self.root, cell, self.stage_digest, resolved, observation, by_task)
        summary = json.loads((self.root / "baselines" / resolved.baseline_id / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["status"], "valid")
        self.assertEqual(len(summary["receipt_digests"]), cell.task_set_size)

    def test_missing_derived_result_is_reconstructed(self) -> None:
        build_complete(self.root, self.cell, self.stage_digest)
        result_path = self.root / "cells" / self.cell.cell_id / "result.json"
        result_path.unlink()
        self.assertEqual(cell_receipt_state(self.root, self.cell, self.stage_digest), "complete")
        self.assertTrue(result_path.is_file())
        self.assertTrue(json.loads(result_path.read_text(encoding="utf-8"))["reconstructed"])

    def test_incoherent_reliability_receipt_is_rejected(self) -> None:
        build_complete(self.root, self.cell, self.stage_digest)
        db = self.root / "runs" / "campaign.sqlite"
        with sqlite3.connect(db) as connection:
            rows = [json.loads(raw) for (raw,) in connection.execute("SELECT receipt_json FROM harness_census_receipts ORDER BY rowid")]
            for receipt in rows:
                if receipt["task_name"] == TASK_IDS[1]:
                    receipt.update({
                        "trial_status": "reliability_failure",
                        "hard_pass": None,
                        "task_points": None,
                        "failure_class": "provider",
                        "failure_stage": "run",
                        "failure_code": "provider_request_failed",
                        "failure_detail_ref": content_ref(
                            bytes_digest((self.root / "exchange" / self.cell.cell_id / TASK_IDS[1] / "trial.json").read_bytes()),
                            f"exchange/{self.cell.cell_id}/{TASK_IDS[1]}/trial.json",
                        ),
                    })
                    receipt.pop("system_identity", None)
            connection.execute("DELETE FROM harness_census_receipts")
            connection.executemany(
                "INSERT INTO harness_census_receipts (campaign_id, receipt_json, crucible_run_id, trial_id, exchange_record_id, cell_run_id) VALUES (?, ?, ?, ?, ?, ?)",
                [(CAMPAIGN_ID, json.dumps(receipt), receipt["crucible_run_id"], receipt["trial_id"], index, receipt["cell_run_id"]) for index, receipt in enumerate(rows, 1)],
            )
            connection.commit()
        with self.assertRaisesRegex(SystemExit, "trial status disagrees"):
            cell_receipt_state(self.root, self.cell, self.stage_digest)

    def test_tampered_grader_bytes_are_rejected(self) -> None:
        build_complete(self.root, self.cell, self.stage_digest)
        grader_path = self.root / "exchange" / self.cell.cell_id / TASK_IDS[0] / "grader.json"
        grader = json.loads(grader_path.read_text(encoding="utf-8"))
        grader["task_points"] = 0.5
        grader_path.write_text(json.dumps(grader), encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "grader"):
            cell_receipt_state(self.root, self.cell, self.stage_digest)

    def test_tampered_transcript_bytes_are_rejected(self) -> None:
        build_complete(self.root, self.cell, self.stage_digest)
        transcript = self.root / "cells" / self.cell.cell_id / "results" / "harbor-jobs" / TASK_IDS[1] / "run" / "trial" / "omp.jsonl"
        transcript.write_bytes(b"tampered\n")
        with self.assertRaisesRegex(SystemExit, "digest mismatch"):
            cell_receipt_state(self.root, self.cell, self.stage_digest)

    def test_stale_result_json_is_rejected(self) -> None:
        build_complete(self.root, self.cell, self.stage_digest)
        result_path = self.root / "cells" / self.cell.cell_id / "result.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["observed_models"] = ["tampered"]
        result_path.write_text(json.dumps(result), encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "stale"):
            cell_receipt_state(self.root, self.cell, self.stage_digest)

    def test_prime_payload_accepts_nested_regular_directories(self) -> None:
        package, metadata = make_prime_package(self.root)
        payload = _prime_payload(package, metadata)
        self.assertEqual(
            set(payload),
            {
                "package.json",
                "dist/bundle/cli.js",
                "dist/prime-agent-runtime/pyproject.toml",
                "dist/prime-agent-runtime/src/rlm/__init__.py",
            },
        )

    def test_prime_payload_accepts_documented_credential_field_names(self) -> None:
        package, metadata = make_prime_package(self.root)
        (package / "dist/bundle/cli.js").write_text("token: 'bearer_exampletoken'\n", encoding="utf-8")
        self.assertIn("dist/bundle/cli.js", _prime_payload(package, metadata))

    def test_prime_payload_rejects_known_secret_prefixes(self) -> None:
        package, metadata = make_prime_package(self.root)
        (package / "dist/bundle/cli.js").write_text("const key = 'sk-realcredential1234567890'\n", encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "secret-like value"):
            _prime_payload(package, metadata)

    def test_prime_payload_ignores_unselected_dependency_examples(self) -> None:
        package, metadata = make_prime_package(self.root)
        example = package / "node_modules/example.js"
        example.parent.mkdir()
        example.write_text("const key = 'sk-examplecredential123456'\n", encoding="utf-8")
        bin_dir = package / "node_modules/.bin"
        bin_dir.mkdir()
        (bin_dir / "prime").symlink_to(example)
        self.assertNotIn("node_modules/example.js", _prime_payload(package, metadata))

    def test_stage_prime_package_copies_the_selected_payload(self) -> None:
        package, _metadata = make_prime_package(self.root)
        staged = Path(stage_prime_package(self.root, package)["path"])
        self.assertTrue((staged / "package.json").is_file())
        self.assertTrue((staged / "dist/bundle/cli.js").is_file())
        self.assertTrue((staged / "package-lock.json").is_file())
        self.assertTrue((staged / "dist/bundle/cli.js").stat().st_mode & 0o111)

    def test_prime_package_rejects_non_executable_cli(self) -> None:
        package, _metadata = make_prime_package(self.root)
        (package / "dist/bundle/cli.js").chmod(0o644)
        with self.assertRaisesRegex(SystemExit, "CLI must be executable"):
            prime_package_info(package)

    def test_node_workers_use_lock_backed_bun_and_pnpm(self) -> None:
        node_toolchain_package_info()
        runtime_package_info("omp")
        runtime_package_info("pi")
        for harness in ("omp", "pi", "prime"):
            package_name = "prime-package" if harness == "prime" else "runtime-package"
            text = dockerfile(harness, package_name, "sploot-hydration-device-lane")
            self.assertNotIn("npm install --global", text)
            self.assertIn("bun --version", text)
            self.assertIn("pnpm --version", text)
        prime_dockerfile = dockerfile("prime", "prime-package", "sploot-hydration-device-lane")
        self.assertIn("COPY runtime-package/ /opt/node-toolchain/", prime_dockerfile)
        self.assertIn("RUN cd /opt/prime-agent && npm ci --omit=dev", prime_dockerfile)
        self.assertIn("RUN /opt/prime-agent/dist/bundle/cli.js --version 2>&1", prime_dockerfile)

    def test_prime_gateway_opens_seccomp_only_for_inner_namespaces(self) -> None:
        normal = self.root / "normal-task"
        prime = self.root / "prime-task"
        write_gateway_assets(normal)
        write_gateway_assets(prime, allow_user_namespaces=True)
        normal_compose = (normal / "environment/docker-compose.yaml").read_text(encoding="utf-8")
        prime_compose = (prime / "environment/docker-compose.yaml").read_text(encoding="utf-8")
        self.assertNotIn("seccomp=unconfined", normal_compose)
        self.assertEqual(prime_compose.count("seccomp=unconfined"), 1)
        self.assertIn("no-new-privileges:true", prime_compose)

    def test_harbor_reward_value_requires_one_bounded_named_reward(self) -> None:
        self.assertEqual(harbor_reward_value({"reward": 0}), 0.0)
        self.assertEqual(harbor_reward_value({"reward": 1.0}), 1.0)
        for value in (0.5, {"score": 0.5}, {"reward": True}, {"reward": -0.1}, {"reward": 1.1}, {"reward": float("nan")}, {"reward": 0.5, "other": 0.5}):
            with self.subTest(value=value):
                self.assertIsNone(harbor_reward_value(value))

    def test_generated_verifier_writes_binary_harbor_reward_map(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            output = root / "verifier"
            workspace.mkdir()
            grader = root / "grader.py"
            grader.write_text(
                "import json\n"
                "def main():\n"
                "    print(json.dumps({'passed': False, 'hard_pass': False, 'passed_checks': 1, 'total_checks': 2, 'task_points': 0.5}))\n"
                "    raise SystemExit(1)\n",
                encoding="utf-8",
            )
            source = verifier_source(grader, {}, ())
            verifier = root / "verify.py"
            verifier.write_text(source, encoding="utf-8")
            run = subprocess.run(
                [sys.executable, str(verifier), str(workspace)],
                env={**os.environ, "HARNESS_CENSUS_LOG_DIR": str(output)},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(run.returncode, 1)
            self.assertEqual(json.loads((output / "reward.json").read_text(encoding="utf-8")), {"reward": 0.0})
            report = json.loads((output / "grader-report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["task_points"], 0.0)
            self.assertEqual(report["grader_report"]["task_points"], 0.5)


    def test_prime_payload_rejects_nested_symlink(self) -> None:
        package, metadata = make_prime_package(self.root)
        link = package / "dist/bundle/linked.js"
        link.symlink_to(package / "dist/bundle/cli.js")
        with self.assertRaisesRegex(SystemExit, "non-regular file"):
            _prime_payload(package, metadata)

    def test_campaign_tree_skips_workspace_symlink_before_safety_check(self) -> None:
        workspace = self.root / "cells" / "omp-controlled_raw" / "tasks" / "task" / "environment" / "repo"
        workspace.mkdir(parents=True)
        target = self.root / "workspace-target"
        target.mkdir()
        (workspace / "linked").symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(SystemExit, "unsafe entry"):
            campaign_tree_files(self.root)
        self.assertEqual(
            campaign_tree_files(self.root, skip=("cells/*/tasks/*/environment/repo/*",)),
            {},
        )

    def _native_partial(self) -> tuple[Cell, dict[str, object]]:
        from dataclasses import replace

        cell = replace(
            self.cell,
            cell_id="omp-native_default",
            cell_run_id=f"{CAMPAIGN_ID}--omp-native_default",
            cell_kind="native_default",
            composition="native_default",
            model_requested=None,
            effort_requested=None,
            provider_route_resolved=None,
            provider_effort_resolved=None,
            default_resolution_source=None,
            effort_source=None,
            row_id=None,
            cohort_id=None,
            baseline_id=None,
            agent_kwargs={"composition": "native_default", "mint_base_url": "http://mint-gateway:4949"},
        )
        record = cell.task_records[0]
        receipt: dict[str, object] = {}
        stage_task_artifacts(self.root, cell, self.stage_digest, record, receipt)
        attestation_path = self.root / "cells" / cell.cell_id / "results" / "harbor-jobs" / record.task_id / "run" / "trial" / "omp.attestation.json"
        attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
        attestation["composition"] = "native_default"
        attestation_path.write_bytes(canonical(attestation))
        result_path = self.root / "exchange" / cell.cell_id / record.task_id / "result.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["evidence"][1]["sha256"] = bytes_digest(canonical(attestation))
        result_path.write_text(json.dumps(result), encoding="utf-8")
        grader_path = self.root / "exchange" / cell.cell_id / record.task_id / "grader.json"
        grader = json.loads(grader_path.read_text(encoding="utf-8"))
        grader.update({"row_id": None, "cohort_id": None})
        model = attestation["observed_identities"][0]
        resolved = cell.resolve_native(model, attestation["effort"], attestation["effort_source"], attestation["tool_manifest_digest"], attestation["config_digest"])
        grader["baseline_id"] = f"sha256:{resolved.baseline_id}"
        grader_path.write_text(json.dumps(grader), encoding="utf-8")
        receipt.update({
            "cell_kind": "native_default",
            "composition": "native_default",
            "model_requested": None,
            "effort_requested": None,
            "provider_route_resolved": model,
            "provider_effort_resolved": attestation["effort"],
            "effort_source": attestation["effort_source"],
            "baseline_id": resolved.baseline_id,
            "row_id": None,
            "cohort_id": None,
            "agent_kwargs_digest": f"sha256:{agent_kwargs_identity_digest(cell.agent_kwargs)}",
            "grader_receipt_ref": content_ref(bytes_digest(grader_path.read_bytes()), grader_path.relative_to(self.root).as_posix()),
            "evidence_refs": [
                receipt["evidence_refs"][0],
                content_ref(bytes_digest(canonical(attestation)), attestation_path.relative_to(self.root).as_posix()),
                receipt["evidence_refs"][2],
            ],
        })
        result_ref = content_ref(bytes_digest(result_path.read_bytes()), result_path.relative_to(self.root).as_posix())
        receipt["result_ref"] = result_ref
        receipt["runner_exchange_result_ref"] = result_ref
        return cell, receipt
    def test_native_partial_resume_keeps_baseline_unresolved(self) -> None:

        cell, receipt = self._native_partial()
        write_db(self.root, [receipt])
        self.assertEqual(receipt_task_ids(self.root, cell), [TASK_IDS[0]])
        self.assertEqual(cell_receipt_state(self.root, cell, self.stage_digest), "partial")
        self.assertEqual(pending_task_ids(self.root, cell), TASK_IDS[1:])

    def test_native_initial_partial_selection_fails_before_provider(self) -> None:
        from dataclasses import replace

        cell = replace(self.cell, cell_kind="native_default", composition="native_default", row_id=None, cohort_id=None, baseline_id=None)
        with self.assertRaisesRegex(SystemExit, "native run requires prior plus selected canonical tasks"):
            run_cell(self.root, cell, Path("/missing/crucible"), Path("/missing/harbor"), self.stage_digest, task_ids=[TASK_IDS[0]], prior_task_ids=[])

    def test_native_observation_requires_three_passes(self) -> None:
        from dataclasses import replace

        cell = replace(
            self.cell,
            cell_kind="native_default",
            composition="native_default",
            row_id=None,
            cohort_id=None,
            baseline_id=None,
        )
        passed = {
            "status": "passed",
            "observed_identities": [CONTROLLED_MODEL],
            "effort": "high",
            "effort_source": "requested",
            "tool_manifest_digest": h64(0xF1),
            "config_digest": h64(0xF2),
        }
        failed = {"status": "failed", "observed_identities": [], "reason": "provider_error"}
        self.assertIsNone(
            native_observation(
                cell,
                [
                    {"task_id": TASK_IDS[0], "record": passed},
                    {"task_id": TASK_IDS[1], "record": failed},
                    {"task_id": TASK_IDS[2], "record": failed},
                ],
            )
        )

    def test_wrong_kind_and_cross_task_attestation_evidence_are_rejected(self) -> None:
        for mutation in ("wrong-kind", "cross-task"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory(prefix="census-evidence-") as temporary:
                root = Path(temporary)
                cell = make_cell(root)
                receipt: dict[str, object] = {}
                record = cell.task_records[0]
                stage_task_artifacts(root, cell, self.stage_digest, record, receipt)
                result_path = root / "exchange" / cell.cell_id / record.task_id / "result.json"
                result = json.loads(result_path.read_text(encoding="utf-8"))
                evidence = result["evidence"][1]
                if mutation == "wrong-kind":
                    evidence["kind"] = "transcript"
                else:
                    evidence["path"] = f"cells/{cell.cell_id}/results/harbor-jobs/{TASK_IDS[1]}/run/trial/omp.attestation.json"
                result_path.write_text(json.dumps(result), encoding="utf-8")
                result_ref = content_ref(bytes_digest(result_path.read_bytes()), result_path.relative_to(root).as_posix())
                receipt["result_ref"] = result_ref
                receipt["runner_exchange_result_ref"] = result_ref
                write_db(root, [receipt])
                with self.assertRaisesRegex(SystemExit, "attestation"):
                    cell_receipt_state(root, cell, self.stage_digest)

    def test_reconstructed_attestation_ref_is_the_adapter_attestation(self) -> None:
        build_complete(self.root, self.cell, self.stage_digest)
        result_path = self.root / "cells" / self.cell.cell_id / "result.json"
        result_path.unlink()
        self.assertEqual(cell_receipt_state(self.root, self.cell, self.stage_digest), "complete")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        attestation_ref = result["attestations"][0]["attestation_ref"]
        self.assertEqual(attestation_ref, f"results/harbor-jobs/{TASK_IDS[0]}/run/trial/omp.attestation.json")
        self.assertEqual(json.loads((self.cell.cell_dir / attestation_ref).read_text(encoding="utf-8"))["schema_version"], "crucible.adapter_attestation.v1")

    def test_setup_error_without_transcript_preserves_root_cause(self) -> None:
        from harness_census_exchange import classify_reliability

        self.assertEqual(
            classify_reliability({"exception_info": {"exception_type": "SetupError"}}, {"status": "failed", "reason": "setup_error"}, None),
            ("harness", "launch", "harbor_job_setup_failed"),
        )

    def test_timeout_without_transcript_remains_retryable(self) -> None:
        from harness_census_exchange import classify_reliability

        failure = classify_reliability({"exception_info": {"exception_type": "TimeoutError"}}, {"status": "failed"}, None)
        self.assertEqual(failure, ("timeout", "run", "adapter_timeout"))
        self.assertIn(failure[0], {"provider", "timeout", "transport"})
    def test_authentication_and_budget_failures_are_not_retryable(self) -> None:
        from harness_census_exchange import classify_reliability

        for exception_type, code in (("AuthenticationError", "provider_authentication_failed"), ("BudgetExceededError", "provider_budget_exceeded")):
            with self.subTest(exception_type=exception_type):
                self.assertEqual(classify_reliability({"exception_info": {"exception_type": exception_type}}, {"status": "failed"}, None), ("provider", "run", code))

    def test_reliability_taxonomy_is_closed_and_reachable(self) -> None:
        from harness_census_common import SUPPORTED_RELIABILITY_CODES
        from harness_census_exchange import classify_reliability

        for code in sorted(SUPPORTED_RELIABILITY_CODES):
            with self.subTest(code=code):
                failure = classify_reliability({"exception_info": {"reliability_code": code}}, {"status": "failed"}, None)
                self.assertIsNotNone(failure)
                self.assertEqual(failure[2], code)
                self.assertIn(failure[2], SUPPORTED_RELIABILITY_CODES)

    def test_unsupported_explicit_failure_code_is_canonicalized(self) -> None:
        from harness_census_exchange import classify_reliability

        for code in ("made_up_failure", "provider_policy_refused_extra"):
            with self.subTest(code=code):
                self.assertEqual(
                    classify_reliability({"exception_info": {"reliability_code": code}}, {"status": "failed"}, None),
                    ("harness", "run", "harbor_execution_failed"),
                )
    def test_guardrail_refusal_is_non_retryable_provider_policy(self) -> None:
        from harness_census_exchange import classify_reliability

        cases = (
            ({"exception_info": {"exception_message": "No endpoints available matching your guardrail restrictions and data policy"}}, {"status": "failed"}),
            ({"exception_info": {"exception_type": "NonZeroAgentExitCodeError"}}, {"status": "failed", "reason": "provider_policy_refused"}),
        )
        for trial, attestation in cases:
            with self.subTest(attestation=attestation):
                self.assertEqual(classify_reliability(trial, attestation, None), ("provider", "run", "provider_policy_refused"))

    def test_memory_ledger_for_generic_runs(self) -> None:
        exchange_source = (ROOT / "scripts/harness_census_exchange.py").read_text(encoding="utf-8")
        self.assertIn('"--db", ":memory:"', exchange_source)
        self.assertNotIn('cell.cell_dir / "runs"', exchange_source)

    def test_staged_task_freezes_worker_and_verifier_images(self) -> None:
        task = load_tasks()[TASK_IDS[0]]
        tag = worker_image_tag("omp", task.id)
        staged, _ = staged_task_toml(task, "controlled_raw", tag)
        self.assertIn(f'docker_image = "{tag}"', staged)
        self.assertIn('environment_mode = "separate"', staged)
        self.assertIn('network_mode = "no-network"', staged)
        compose = compose_yaml(worker_image=tag)
        self.assertIn(f"    image: {tag}\n", compose)
        self.assertNotIn("dockerfile: Dockerfile", compose)

    def test_mutated_pending_workspace_is_refused(self) -> None:
        source = self.cell.cell_dir / "tasks" / TASK_IDS[0] / "environment" / "repo"
        source.mkdir(parents=True)
        (source / "changed.txt").write_text("mutated", encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "source identity changed"):
            verify_pending_task_sources(self.root, self.cell, [TASK_IDS[0]])
    def test_context_pack_has_no_write_only_artifact_paths(self) -> None:
        context_source = (ROOT / "scripts/harness_census_context.py").read_text(encoding="utf-8")
        for marker in ("/blobs/", "/archive/", "context-manifest.json"):
            self.assertNotIn(marker, context_source)

    def test_worker_image_excludes_verifier_mount(self) -> None:
        self.assertNotIn("COPY tests", dockerfile("omp", "runtime-package", TASK_IDS[0]))


    def test_controlled_receipt_requires_treatment_identity(self) -> None:
        build_complete(self.root, self.cell, self.stage_digest)
        db = self.root / "runs" / "campaign.sqlite"
        with sqlite3.connect(db) as connection:
            raw, run_id = connection.execute(
                "SELECT receipt_json, crucible_run_id FROM harness_census_receipts ORDER BY rowid LIMIT 1"
            ).fetchone()
            receipt = json.loads(raw)
            for key in (
                "crucible_run_id", "model_requested", "effort_requested", "provider_route_resolved",
                "provider_effort_resolved", "row_id", "cohort_id", "profile_digest",
            ):
                with self.subTest(key=key):
                    changed = dict(receipt)
                    changed.pop(key)
                    connection.execute(
                        "UPDATE harness_census_receipts SET receipt_json = ? WHERE crucible_run_id = ?",
                        (json.dumps(changed), run_id),
                    )
                    connection.commit()
                    with self.assertRaisesRegex(SystemExit, "identity mismatch"):
                        cell_receipt_state(self.root, self.cell, self.stage_digest)
                    connection.execute(
                        "UPDATE harness_census_receipts SET receipt_json = ? WHERE crucible_run_id = ?",
                        (raw, run_id),
                    )
                    connection.commit()

    def test_trial_run_identity_is_verified_after_content_rebind(self) -> None:
        build_complete(self.root, self.cell, self.stage_digest)
        trial_path = self.root / "exchange" / self.cell.cell_id / TASK_IDS[0] / "trial.json"
        old_ref = content_ref(bytes_digest(trial_path.read_bytes()), trial_path.relative_to(self.root).as_posix())
        trial = json.loads(trial_path.read_text(encoding="utf-8"))
        trial["crucible_run_id"] = "wrong-run"
        trial_path.write_text(json.dumps(trial), encoding="utf-8")
        new_ref = content_ref(bytes_digest(trial_path.read_bytes()), trial_path.relative_to(self.root).as_posix())
        db = self.root / "runs" / "campaign.sqlite"
        with sqlite3.connect(db) as connection:
            raw, run_id = connection.execute(
                "SELECT receipt_json, crucible_run_id FROM harness_census_receipts ORDER BY rowid LIMIT 1"
            ).fetchone()
            receipt = json.loads(raw)
            receipt["evidence_refs"] = [new_ref if value == old_ref else value for value in receipt["evidence_refs"]]
            connection.execute(
                "UPDATE harness_census_receipts SET receipt_json = ? WHERE crucible_run_id = ?",
                (json.dumps(receipt), run_id),
            )
            connection.commit()
        with self.assertRaisesRegex(SystemExit, "trial artifact identity mismatch"):
            cell_receipt_state(self.root, self.cell, self.stage_digest)

    def test_database_receipt_run_linkage_is_verified(self) -> None:
        build_complete(self.root, self.cell, self.stage_digest)
        db = self.root / "runs" / "campaign.sqlite"
        with sqlite3.connect(db) as connection:
            target_run_id = f"{CAMPAIGN_ID}--{self.cell.cell_id}--{TASK_IDS[0]}"
            connection.execute(
                "UPDATE harness_census_receipts SET crucible_run_id = ? WHERE crucible_run_id = ?",
                ("wrong-run", target_run_id),
            )
            connection.commit()
        with self.assertRaisesRegex(SystemExit, "database receipt identity mismatch"):
            cell_receipt_state(self.root, self.cell, self.stage_digest)

    def test_reliability_trial_treatment_is_verified_after_content_rebind(self) -> None:
        build_complete(self.root, self.cell, self.stage_digest)
        install_reliability_receipt(self.root, self.cell, retryable=False)
        trial_path = self.root / "exchange" / self.cell.cell_id / TASK_IDS[1] / "trial.json"
        old_ref = content_ref(bytes_digest(trial_path.read_bytes()), trial_path.relative_to(self.root).as_posix())
        trial = json.loads(trial_path.read_text(encoding="utf-8"))
        trial["provider_effort_resolved"] = "low"
        trial_path.write_text(json.dumps(trial), encoding="utf-8")
        new_ref = content_ref(bytes_digest(trial_path.read_bytes()), trial_path.relative_to(self.root).as_posix())
        db = self.root / "runs" / "campaign.sqlite"
        with sqlite3.connect(db) as connection:
            target_run_id = f"{CAMPAIGN_ID}--{self.cell.cell_id}--{TASK_IDS[1]}"
            raw, run_id = connection.execute(
                "SELECT receipt_json, crucible_run_id FROM harness_census_receipts WHERE crucible_run_id = ?",
                (target_run_id,),
            ).fetchone()
            receipt = json.loads(raw)
            receipt["evidence_refs"] = [new_ref if value == old_ref else value for value in receipt["evidence_refs"]]
            connection.execute(
                "UPDATE harness_census_receipts SET receipt_json = ? WHERE crucible_run_id = ?",
                (json.dumps(receipt), run_id),
            )
            connection.commit()
        with self.assertRaisesRegex(SystemExit, "trial treatment identity mismatch"):
            cell_receipt_state(self.root, self.cell, self.stage_digest)

    def test_coherent_reliability_receipt_invalidates_cell(self) -> None:
        build_complete(self.root, self.cell, self.stage_digest)
        install_reliability_receipt(self.root, self.cell, retryable=False)
        self.assertEqual(cell_receipt_state(self.root, self.cell, self.stage_digest), "invalid")

    def test_reliability_failure_detail_content_is_verified(self) -> None:
        build_complete(self.root, self.cell, self.stage_digest)
        install_reliability_receipt(self.root, self.cell, retryable=False)
        detail_path = self.root / "cells" / self.cell.cell_id / "results" / "harbor-jobs" / TASK_IDS[1] / "run" / "trial" / "result.json"
        detail_path.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "failure_detail_ref content digest mismatch"):
            cell_receipt_state(self.root, self.cell, self.stage_digest)

    def test_reliability_result_retryability_is_verified(self) -> None:
        build_complete(self.root, self.cell, self.stage_digest)
        install_reliability_receipt(self.root, self.cell, retryable=True)
        with self.assertRaisesRegex(SystemExit, "reliability result disagrees"):
            cell_receipt_state(self.root, self.cell, self.stage_digest)


if __name__ == "__main__":
    unittest.main()
