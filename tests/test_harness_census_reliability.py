from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from harness_census_common import CAMPAIGN_ID, bytes_digest, digest
from harness_census_exchange import exchange_envelopes
from harness_census_resume import cell_receipt_state
from harness_census_test_support import TASK_IDS, build_complete, content_ref, h64, install_reliability_receipt, make_cell


class ReliabilityReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="census-reliability-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cell = make_cell(self.root)
        self.stage_digest = h64(0xFF)


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
        attestation.update({
            "status": "passed",
            "observed_identities": [cell.provider_route_resolved],
            "effort": cell.provider_effort_resolved,
            "effort_source": cell.effort_source,
            "fallback_count": 0,
            "turn_count": 3,
        })
        attestation.pop("reason")
        attestation_path.write_text(json.dumps(attestation), encoding="utf-8")
        entry["record"] = attestation
        verifier = trial_dir / "verifier"
        transcript_path = trial_dir / "omp.jsonl"
        transcript_path.write_text("{}\n", encoding="utf-8")
        entry["transcript_ref"] = transcript_path.relative_to(cell.cell_dir).as_posix()
        entry["transcript_path"] = transcript_path
        verifier.mkdir()
        (verifier / "grader-report.json").write_text("{}", encoding="utf-8")
        (verifier / "test-stdout.txt").write_text("passed\n", encoding="utf-8")
        (trial_dir / "result.json").write_text(json.dumps({"task_name": record.task_id, "started_at": "2026-08-09T00:00:00Z", "finished_at": "2026-08-09T00:00:01Z"}), encoding="utf-8")
        (verifier / "reward.json").write_text(json.dumps({"reward": 1.0}), encoding="utf-8")
        succeeded = exchange_envelopes(self.root, cell, record, trial_dir, entry, self.stage_digest, None)
        self.assertEqual(json.loads(succeeded.trial.read_text(encoding="utf-8"))["trial_status"], "success")
        (verifier / "reward.json").write_text(json.dumps({"reward": 0.5}), encoding="utf-8")
        quality_failed = exchange_envelopes(self.root, cell, record, trial_dir, entry, self.stage_digest, None)
        self.assertEqual(json.loads(quality_failed.trial.read_text(encoding="utf-8"))["trial_status"], "quality_failure")
        (trial_dir / "result.json").write_text(json.dumps({"task_name": record.task_id}), encoding="utf-8")
        malformed = exchange_envelopes(self.root, cell, record, trial_dir, entry, self.stage_digest, None, ("2026-08-09T00:00:00Z", "2026-08-09T00:00:01Z"))
        malformed_trial = json.loads(malformed.trial.read_text(encoding="utf-8"))
        self.assertEqual(malformed_trial["failure_code"], "harbor_trial_malformed")
        self.assertEqual(malformed_trial["failure_detail"]["timestamp_fallback_source"], "bench_cell_subprocess_bounds")
    def test_incoherent_reliability_receipt_is_rejected(self) -> None:
        build_complete(self.root, self.cell, self.stage_digest)
        db = self.root / "runs" / "campaign.sqlite"
        with sqlite3.connect(db) as connection:
            rows = [json.loads(raw) for (raw,) in connection.execute("SELECT receipt_json FROM harness_census_receipts ORDER BY rowid")]
            for receipt in rows:
                if receipt["task_id"] == TASK_IDS[1]:
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

    def test_reliability_failure_detail_is_the_canonical_harbor_trial(self) -> None:
        build_complete(self.root, self.cell, self.stage_digest)
        install_reliability_receipt(self.root, self.cell, retryable=False)
        canonical = self.root / "cells" / self.cell.cell_id / "results" / "harbor-jobs" / TASK_IDS[1] / "run" / "trial" / "result.json"
        alternate = canonical.parent.parent / "alternate" / "result.json"
        alternate.parent.mkdir()
        alternate.write_bytes(canonical.read_bytes())
        alternate_ref = content_ref(bytes_digest(alternate.read_bytes()), alternate.relative_to(self.root).as_posix())
        db = self.root / "runs" / "campaign.sqlite"
        with sqlite3.connect(db) as connection:
            target_run_id = f"{CAMPAIGN_ID}--{self.cell.cell_id}--{TASK_IDS[1]}"
            raw = connection.execute("SELECT receipt_json FROM harness_census_receipts WHERE crucible_run_id = ?", (target_run_id,)).fetchone()[0]
            receipt = json.loads(raw)
            receipt["failure_detail_ref"] = alternate_ref
            receipt["evidence_refs"].append(alternate_ref)
            connection.execute("UPDATE harness_census_receipts SET receipt_json = ? WHERE crucible_run_id = ?", (json.dumps(receipt), target_run_id))
            connection.commit()
        with self.assertRaisesRegex(SystemExit, "invalid failure_detail_ref"):
            cell_receipt_state(self.root, self.cell, self.stage_digest)

    def test_reliability_result_retryability_is_verified(self) -> None:
        build_complete(self.root, self.cell, self.stage_digest)
        install_reliability_receipt(self.root, self.cell, retryable=True)
        with self.assertRaisesRegex(SystemExit, "reliability result disagrees"):
            cell_receipt_state(self.root, self.cell, self.stage_digest)
if __name__ == "__main__":
    unittest.main()
