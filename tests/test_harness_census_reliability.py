from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from test_harness_census_resume import TASK_IDS, build_complete, content_ref, h64, make_cell
from harness_census_common import Cell, bytes_digest
from harness_census_resume import cell_receipt_state


def install_reliability_receipt(root: Path, cell: Cell, *, retryable: bool) -> None:
    db = root / "runs" / "campaign.sqlite"
    with sqlite3.connect(db) as connection:
        raw = connection.execute(
            "SELECT receipt_json FROM harness_census_receipts WHERE receipt_json LIKE ?",
            (f'%"task_name": "{TASK_IDS[1]}"%',),
        ).fetchone()[0]
        receipt = json.loads(raw)

        task_exchange = root / "exchange" / cell.cell_id / TASK_IDS[1]
        trial_path = task_exchange / "trial.json"
        trial = json.loads(trial_path.read_text(encoding="utf-8"))
        failure_detail = {"failure_code": "provider_policy_refused", "reason": "policy refusal"}
        trial.update({
            "trial_status": "reliability_failure",
            "failure_class": "provider",
            "failure_stage": "run",
            "failure_code": "provider_policy_refused",
            "failure_detail": failure_detail,
        })
        trial_path.write_text(json.dumps(trial), encoding="utf-8")

        result_path = task_exchange / "result.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["status"] = "execution_error"
        result.pop("output", None)
        result["error"] = {
            "code": "provider_policy_refused",
            "message": "policy refusal",
            "retryable": retryable,
            "detail": failure_detail,
        }
        result_path.write_text(json.dumps(result), encoding="utf-8")

        trial_relative = trial_path.relative_to(root).as_posix()
        trial_ref = content_ref(bytes_digest(trial_path.read_bytes()), trial_relative)
        result_ref = content_ref(bytes_digest(result_path.read_bytes()), result_path.relative_to(root).as_posix())
        receipt.update({
            "trial_status": "reliability_failure",
            "hard_pass": None,
            "task_points": None,
            "failure_class": "provider",
            "failure_stage": "run",
            "failure_code": "provider_policy_refused",
            "failure_detail_ref": trial_ref,
            "runner_exchange_result_ref": result_ref,
            "result_ref": result_ref,
        })
        receipt.pop("system_identity", None)
        receipt["evidence_refs"] = [
            trial_ref if isinstance(value, str) and value.endswith(f"@{trial_relative}") else value
            for value in receipt["evidence_refs"]
        ]
        connection.execute(
            "UPDATE harness_census_receipts SET receipt_json = ? WHERE crucible_run_id = ?",
            (json.dumps(receipt), receipt["crucible_run_id"]),
        )
        connection.commit()
    (root / "cells" / cell.cell_id / "result.json").unlink()


class ReliabilityReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="census-reliability-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cell = make_cell(self.root)
        self.stage_digest = h64(0xFF)
        build_complete(self.root, self.cell, self.stage_digest)

    def test_controlled_receipt_requires_treatment_identity(self) -> None:
        db = self.root / "runs" / "campaign.sqlite"
        with sqlite3.connect(db) as connection:
            raw, run_id = connection.execute(
                "SELECT receipt_json, crucible_run_id FROM harness_census_receipts ORDER BY rowid LIMIT 1"
            ).fetchone()
            receipt = json.loads(raw)
            for key in (
                "model_requested", "effort_requested", "provider_route_resolved",
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

    def test_coherent_reliability_receipt_invalidates_cell(self) -> None:
        install_reliability_receipt(self.root, self.cell, retryable=False)
        self.assertEqual(cell_receipt_state(self.root, self.cell, self.stage_digest), "invalid")

    def test_reliability_result_retryability_is_verified(self) -> None:
        install_reliability_receipt(self.root, self.cell, retryable=True)
        with self.assertRaisesRegex(SystemExit, "reliability result disagrees"):
            cell_receipt_state(self.root, self.cell, self.stage_digest)


if __name__ == "__main__":
    unittest.main()
