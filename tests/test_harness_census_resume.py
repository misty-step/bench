from __future__ import annotations

import json
from pathlib import Path
import sqlite3
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
    canonical,
    digest,
    load_tasks,
    mcp_identity_digest,
)
from harness_census_staging import cell_receipt_state, pending_task_ids


TASK_IDS = sorted((
    "estate-pagination-origin",
    "iron-forest-go-checkruns-array",
    "sploot-hydration-device-lane",
))


def h64(number: int) -> str:
    return f"{number:064x}"


def content_ref(value: str, relative: str) -> str:
    return f"sha256:{value}@{relative}"


def make_cell(root: Path) -> Cell:
    records = tuple(
        TaskRecord(
            task_id=task_id,
            task_digest=h64(0x10 + index),
            comparison_task_digest=h64(0x20 + index),
            source_tree_digest=h64(0x30 + index),
            grader_digest=h64(0x40 + index),
            reference_hunk_map_digest=h64(0x50 + index),
            dockerfile_digest=h64(0x60 + index),
            gateway_digest=h64(0x70 + index),
            gateway_dockerfile_digest=h64(0x80 + index),
            compose_digest=h64(0x90 + index),
            prime_package_digest=None,
            task_dir=f"tasks/{task_id}",
            allowed_paths=("src",),
            immutable_paths=("src/a",),
            network_mode="docker_internal_mint_gateway",
            context_manifest_digest=h64(0xA0 + index),
            context_pack_digest=h64(0xB0 + index),
            skill_digest=h64(0xC0 + index),
            context_digest=h64(0xD0 + index),
            skill_count=0,
        )
        for index, task_id in enumerate(TASK_IDS)
    )
    return Cell(
        cell_id="omp-controlled_raw",
        cell_run_id=f"{CAMPAIGN_ID}--omp-controlled_raw",
        task_set_digest=h64(0xE0),
        task_set_size=3,
        retry_policy_digest=h64(0xE1),
        agent_kwargs_base_digest=h64(0xE2),
        cell_dir=root / "cells" / "omp-controlled_raw",
        spec_path=root / "cells" / "omp-controlled_raw" / "eval.json",
        cell_kind="controlled",
        harness="omp",
        harness_version="17.2.11",
        composition="controlled_raw",
        model_requested=CONTROLLED_MODEL,
        effort_requested=CONTROLLED_EFFORT,
        provider_route_resolved=CONTROLLED_MODEL,
        provider_effort_resolved=CONTROLLED_EFFORT,
        default_resolution_source=None,
        effort_source="requested",
        row_id=h64(0xE3),
        cohort_id=h64(0xE4),
        baseline_id=None,
        profile_digest=h64(0xE5),
        agent_kwargs={
            "mint_base_url": "http://mint-gateway:4949",
            "composition": "controlled_raw",
            "thinking": "high",
        },
        agent_allowed_hosts=("mint-gateway",),
        network_mode="docker_internal_mint_gateway",
        transport_network_mode="host",
        network_enforcement="docker_internal_mint_gateway",
        task_network_enforcement="deny",
        task_digest=h64(0xE6),
        composition_digest=h64(0xE7),
        adapter_digest=h64(0xE8),
        package_digest=h64(0xE9),
        prime_package_digest=None,
        dockerfile_digests=tuple(h64(0x60 + index) for index in range(3)),
        gateway_digests=tuple(h64(0x70 + index) for index in range(3)),
        gateway_dockerfile_digests=tuple(h64(0x80 + index) for index in range(3)),
        compose_digests=tuple(h64(0x90 + index) for index in range(3)),
        task_records=records,
    )


def task_source_cluster(task_id: str) -> str:
    return load_tasks()[task_id].source_cluster


def stage_task_artifacts(
    root: Path,
    cell: Cell,
    stage_digest: str,
    record: TaskRecord,
    receipt: dict[str, object],
) -> None:
    task_exchange = root / "exchange" / cell.cell_id / record.task_id
    task_exchange.mkdir(parents=True, exist_ok=True)
    run_id = f"{CAMPAIGN_ID}--{cell.cell_id}--{record.task_id}"
    exchange_id = f"{run_id}--{record.task_id}"
    instruction_path = f"cells/{cell.cell_id}/{record.task_dir}/instruction.md"
    request = {
        "schema_version": "crucible.runner_exchange_request.v1",
        "exchange_id": exchange_id,
        "task_id": record.task_id,
        "cell_id": cell.cell_id,
        "cell_run_id": cell.cell_run_id,
        "task_set_digest": f"sha256:{cell.task_set_digest}",
        "task_set_size": 3,
        "retry_policy_digest": f"sha256:{cell.retry_policy_digest}",
        "agent_kwargs_base_digest": f"sha256:{cell.agent_kwargs_base_digest}",
        "adapter": {
            "name": "crucible.harbor_agents.omp",
            "version": "17.2.11",
            "digest": f"sha256:{cell.adapter_digest}",
        },
        "candidate": {
            "kind": "agent",
            "harness": "omp",
            "harness_version": "17.2.11",
            "model": {"provider": "openrouter", "name": "deepseek/deepseek-v4-flash-0731"},
            "reasoning_effort": "high",
        },
        "capabilities": ["workspace_edit"],
        "input": {
            "workspace": f"cells/{cell.cell_id}/{record.task_dir}/environment/repo",
            "instruction": instruction_path,
            "context": [],
            "digest": f"sha256:{h64(0xF0)}",
        },
        "authority": {"filesystem_roots": [], "network": "deny", "allowed_hosts": [], "credential_refs": []},
        "limits": {
            "timeout_ms": 900000,
            "max_output_bytes": 1048576,
            "cpu_millicores": 1000,
            "memory_mb": 1024,
            "storage_mb": 2048,
        },
        "provenance": {
            "repo": "misty-step/estate",
            "git_sha": "a" * 40,
            "invocation_id": exchange_id,
        },
        "trust": {
            "required_evidence_kinds": [],
            "require_transcript": False,
            "require_usage": False,
            "require_cost": False,
            "require_response_model": False,
        },
        "adapter_payload": {},
    }
    for key in ("dockerfile_digest", "gateway_digest", "gateway_dockerfile_digest", "compose_digest"):
        request[key] = f"sha256:{getattr(record, key)}"

    trial_ref = f"exchange/{cell.cell_id}/{record.task_id}/trial.json"
    attestation_path = f"cells/{cell.cell_id}/results/harbor-jobs/{record.task_id}/run/trial/omp.attestation.json"
    attestation = {
        "schema_version": "crucible.adapter_attestation.v1",
        "status": "passed",
        "adapter": "omp",
        "composition": "controlled_raw",
        "version": "17.2.11",
        "observed_identities": [CONTROLLED_MODEL],
        "effort": "high",
        "effort_source": "requested",
        "fallback_count": 0,
        "turn_count": 3,
        "tool_manifest_digest": h64(0xF1),
        "config_digest": h64(0xF2),
    }
    transcript_rel = f"cells/{cell.cell_id}/results/harbor-jobs/{record.task_id}/run/trial/omp.jsonl"
    transcript_bytes = b"turn 1\n"
    evidence = [
        {"kind": "harbor_trial", "path": trial_ref, "sha256": "0" * 64, "media_type": "application/json"},
        {"kind": "attestation", "path": attestation_path, "sha256": bytes_digest(canonical(attestation)), "media_type": "application/json"},
        {"kind": "transcript", "path": transcript_rel, "sha256": bytes_digest(transcript_bytes), "media_type": "application/x-ndjson"},
    ]
    result = {
        "schema_version": "crucible.runner_exchange_result.v1",
        "exchange_id": exchange_id,
        "cell_id": cell.cell_id,
        "cell_run_id": cell.cell_run_id,
        "adapter": request["adapter"],
        "candidate": request["candidate"],
        "status": "success",
        "output": {"summary": "ok", "primary_artifact": trial_ref},
        "evidence": evidence,
        "usage": {"input_tokens": 1, "output_tokens": 1, "cache_tokens": 0, "cost_usd": 0.0, "latency_ms": 1},
        "provenance": {"response_model": CONTROLLED_MODEL, "started_at": "2026-08-09T00:00:00Z", "finished_at": "2026-08-09T00:00:01Z"},
        "adapter_payload": {"composition_digest": f"sha256:{cell.composition_digest}"},
    }
    for key in ("dockerfile_digest", "gateway_digest", "gateway_dockerfile_digest", "compose_digest"):
        result[key] = f"sha256:{getattr(record, key)}"

    trial = {
        "schema_version": "harness_census.trial_receipt.v1",
        "campaign_id": CAMPAIGN_ID,
        "trial_id": f"{cell.cell_id}--{record.task_id}",
        "crucible_run_id": run_id,
        "cell_id": cell.cell_id,
        "cell_run_id": cell.cell_run_id,
        "task_set_digest": f"sha256:{cell.task_set_digest}",
        "task_set_size": 3,
        "retry_policy_digest": f"sha256:{cell.retry_policy_digest}",
        "agent_kwargs_base_digest": f"sha256:{cell.agent_kwargs_base_digest}",
        "source_cluster": task_source_cluster(record.task_id),
        "task_name": record.task_id,
        "stage_manifest_digest": f"sha256:{stage_digest}",
        "network_mode": "docker_internal_mint_gateway",
        "task_id": record.task_id,
        "row_id": f"sha256:{cell.row_id}",
        "cohort_id": f"sha256:{cell.cohort_id}",
        "baseline_id": None,
        "profile_digest": f"sha256:{cell.profile_digest}",
        "model_requested": CONTROLLED_MODEL,
        "effort_requested": CONTROLLED_EFFORT,
        "provider_route_resolved": CONTROLLED_MODEL,
        "provider_effort_resolved": CONTROLLED_EFFORT,
        "context_digest": f"sha256:{record.context_digest}",
        "context_manifest_digest": f"sha256:{record.context_manifest_digest}",
        "context_pack_digest": f"sha256:{record.context_pack_digest}",
        "skill_digest": f"sha256:{record.skill_digest}",
        "comparison_task_digest": f"sha256:{record.comparison_task_digest}",
        "assistant_turns": 3,
    }
    for key in ("dockerfile_digest", "gateway_digest", "gateway_dockerfile_digest", "compose_digest"):
        trial[key] = f"sha256:{getattr(record, key)}"

    request_path = task_exchange / "request.json"
    result_path = task_exchange / "result.json"
    trial_path = task_exchange / "trial.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    result_path.write_text(json.dumps(result), encoding="utf-8")
    trial_path.write_text(json.dumps(trial), encoding="utf-8")
    grader = {
        "schema_version": "harness_census.grader_receipt.v1",
        "campaign_id": CAMPAIGN_ID,
        "trial_id": f"{cell.cell_id}--{record.task_id}",
        "task_id": record.task_id,
        "row_id": f"sha256:{cell.row_id}",
        "cohort_id": f"sha256:{cell.cohort_id}",
        "baseline_id": None,
        "profile_digest": f"sha256:{cell.profile_digest}",
        "grader_identity": "harness_census_deterministic",
        "grader_digest": record.grader_digest,
        "hard_pass": True,
        "task_points": 1.0,
        "grader_ms": None,
    }
    grader_path = task_exchange / "grader.json"
    grader_path.write_text(json.dumps(grader), encoding="utf-8")
    attestation_file = root / Path(attestation_path)
    attestation_file.parent.mkdir(parents=True, exist_ok=True)
    attestation_file.write_bytes(canonical(attestation))
    transcript_file = root / Path(transcript_rel)
    transcript_file.parent.mkdir(parents=True, exist_ok=True)
    transcript_file.write_bytes(transcript_bytes)

    receipt.update({
        "schema_version": "harness_census.trial_receipt.v1",
        "campaign_id": CAMPAIGN_ID,
        "trial_id": f"{cell.cell_id}--{record.task_id}",
        "crucible_run_id": run_id,
        "cell_id": cell.cell_id,
        "cell_run_id": cell.cell_run_id,
        "task_set_digest": f"sha256:{cell.task_set_digest}",
        "task_set_size": 3,
        "retry_policy_digest": f"sha256:{cell.retry_policy_digest}",
        "agent_kwargs_base_digest": f"sha256:{cell.agent_kwargs_base_digest}",
        "source_cluster": task_source_cluster(record.task_id),
        "task_name": record.task_id,
        "task_id": record.task_id,
        "stage_manifest_digest": f"sha256:{stage_digest}",
        "cell_kind": "controlled",
        "composition": "controlled_raw",
        "harness": "omp",
        "harness_version": "17.2.11",
        "model_requested": CONTROLLED_MODEL,
        "effort_requested": CONTROLLED_EFFORT,
        "provider_route_resolved": CONTROLLED_MODEL,
        "provider_effort_resolved": CONTROLLED_EFFORT,
        "composition_digest": f"sha256:{cell.composition_digest}",
        "adapter_digest": f"sha256:{cell.adapter_digest}",
        "mcp_digest": f"sha256:{mcp_identity_digest()}",
        "agent_kwargs_digest": f"sha256:{agent_kwargs_identity_digest(cell.agent_kwargs)}",
        "agent_allowed_hosts_digest": f"sha256:{agent_allowed_hosts_identity_digest(cell)}",
        "gateway_digests": list(cell.gateway_digests),
        "gateway_dockerfile_digests": list(cell.gateway_dockerfile_digests),
        "compose_digests": list(cell.compose_digests),
        "context_manifest_digest": f"sha256:{record.context_manifest_digest}",
        "context_pack_digest": f"sha256:{record.context_pack_digest}",
        "context_digest": f"sha256:{record.context_digest}",
        "skill_digest": f"sha256:{record.skill_digest}",
        "skill_count": 0,
        "task_digest": f"sha256:{record.task_digest}",
        "comparison_task_digest": f"sha256:{record.comparison_task_digest}",
        "row_id": f"sha256:{cell.row_id}",
        "cohort_id": f"sha256:{cell.cohort_id}",
        "baseline_id": None,
        "profile_digest": f"sha256:{cell.profile_digest}",
        "dockerfile_digest": f"sha256:{record.dockerfile_digest}",
        "gateway_digest": f"sha256:{record.gateway_digest}",
        "gateway_dockerfile_digest": f"sha256:{record.gateway_dockerfile_digest}",
        "compose_digest": f"sha256:{record.compose_digest}",
        "runner_exchange_request_ref": content_ref(bytes_digest(request_path.read_bytes()), f"exchange/{cell.cell_id}/{record.task_id}/request.json"),
        "runner_exchange_result_ref": content_ref(bytes_digest(result_path.read_bytes()), f"exchange/{cell.cell_id}/{record.task_id}/result.json"),
        "request_ref": content_ref(bytes_digest(request_path.read_bytes()), f"exchange/{cell.cell_id}/{record.task_id}/request.json"),
        "result_ref": content_ref(bytes_digest(result_path.read_bytes()), f"exchange/{cell.cell_id}/{record.task_id}/result.json"),
        "grader_receipt_ref": content_ref(bytes_digest(grader_path.read_bytes()), f"exchange/{cell.cell_id}/{record.task_id}/grader.json"),
        "transcript_ref": content_ref(bytes_digest(transcript_bytes), transcript_rel),
        "evidence_refs": [
            content_ref(bytes_digest(trial_path.read_bytes()), trial_ref),
            content_ref(bytes_digest(canonical(attestation)), attestation_path),
            content_ref(bytes_digest(transcript_bytes), transcript_rel),
        ],
        "tool_manifest_digest": h64(0xF1),
        "system_identity": digest({"config_digest": h64(0xF2), "tool_manifest_digest": h64(0xF1)}),
        "trial_status": "success",
        "hard_pass": True,
        "task_points": 1.0,
    })


def write_db(root: Path, receipts: list[dict[str, object]]) -> None:
    db = root / "runs" / "campaign.sqlite"
    db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE harness_census_receipts (campaign_id TEXT, receipt_json TEXT, crucible_run_id TEXT, exchange_record_id INTEGER, cell_run_id TEXT)")
        connection.execute("CREATE TABLE runner_exchange_records (record_id INTEGER PRIMARY KEY, exchange_id TEXT)")
        connection.execute("CREATE TABLE run_records (run_id TEXT PRIMARY KEY, trusted INTEGER)")
        for index, receipt in enumerate(receipts, 1):
            connection.execute("INSERT INTO runner_exchange_records (record_id, exchange_id) VALUES (?, ?)", (index, receipt["trial_id"]))
            connection.execute(
                "INSERT INTO harness_census_receipts (campaign_id, receipt_json, crucible_run_id, exchange_record_id, cell_run_id) VALUES (?, ?, ?, ?, ?)",
                (CAMPAIGN_ID, json.dumps(receipt), receipt["crucible_run_id"], index, receipt["cell_run_id"]),
            )
        connection.execute("INSERT INTO run_records (run_id, trusted) VALUES (?, ?)", (receipts[0]["cell_run_id"], 1))
        connection.commit()


def build_complete(root: Path, cell: Cell, stage_digest: str) -> None:
    receipts: list[dict[str, object]] = []
    for record in cell.task_records:
        receipt: dict[str, object] = {}
        stage_task_artifacts(root, cell, stage_digest, record, receipt)
        receipts.append(receipt)
    write_db(root, receipts)
    from harness_census_staging import _derive_cell_result

    result = _derive_cell_result(root, cell, stage_digest, {receipt["task_name"]: (receipt, 1) for receipt in receipts}, None)
    result_path = root / "cells" / cell.cell_id / "result.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result), encoding="utf-8")


class HarnessCensusResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="census-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cell = make_cell(self.root)
        self.stage_digest = h64(0xFF)

    def test_absent_cell_selects_all_tasks(self) -> None:
        self.assertEqual(cell_receipt_state(self.root, self.cell, self.stage_digest), "absent")
        self.assertEqual(pending_task_ids(self.root, self.cell), TASK_IDS)

    def test_one_valid_receipt_is_partial_with_two_pending_tasks(self) -> None:
        receipt: dict[str, object] = {}
        stage_task_artifacts(self.root, self.cell, self.stage_digest, self.cell.task_records[0], receipt)
        write_db(self.root, [receipt])
        self.assertEqual(cell_receipt_state(self.root, self.cell, self.stage_digest), "partial")
        self.assertEqual(pending_task_ids(self.root, self.cell), TASK_IDS[1:])

    def test_three_valid_receipts_are_complete(self) -> None:
        build_complete(self.root, self.cell, self.stage_digest)
        self.assertEqual(cell_receipt_state(self.root, self.cell, self.stage_digest), "complete")
        self.assertEqual(pending_task_ids(self.root, self.cell), [])

    def test_missing_derived_result_is_reconstructed(self) -> None:
        build_complete(self.root, self.cell, self.stage_digest)
        result_path = self.root / "cells" / self.cell.cell_id / "result.json"
        result_path.unlink()
        self.assertEqual(cell_receipt_state(self.root, self.cell, self.stage_digest), "complete")
        self.assertTrue(result_path.is_file())
        self.assertTrue(json.loads(result_path.read_text(encoding="utf-8"))["reconstructed"])

    def test_reliability_receipt_invalidates_cell(self) -> None:
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
                "INSERT INTO harness_census_receipts (campaign_id, receipt_json, crucible_run_id, exchange_record_id, cell_run_id) VALUES (?, ?, ?, ?, ?)",
                [(CAMPAIGN_ID, json.dumps(receipt), receipt["crucible_run_id"], index, receipt["cell_run_id"]) for index, receipt in enumerate(rows, 1)],
            )
            connection.commit()
        (self.root / "cells" / self.cell.cell_id / "result.json").unlink()
        self.assertEqual(cell_receipt_state(self.root, self.cell, self.stage_digest), "invalid")

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


if __name__ == "__main__":
    unittest.main()
