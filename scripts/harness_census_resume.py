"""Validate canonical receipts and resume frozen Harness Census cells."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from harness_census_common import (
    CAMPAIGN_ID,
    RETRYABLE_RELIABILITY_CODES,
    SUPPORTED_RELIABILITY_CODES,
    Cell,
    TaskRecord,
    agent_allowed_hosts_identity_digest,
    agent_kwargs_identity_digest,
    _valid_digest,
    bytes_digest,
    campaign_tree_files,
    cell_stage_digest,
    compact_receipt,
    confined_path,
    digest,
    fail,
    file_digest,
    load_tasks,
    mcp_identity_digest,
    reference_hunk_map_digest,
    reliability_failure_identity,
    task_corpus_identity,
    tree_digest,
    write_json,
)


def _matches_ref(value: object, expected: object) -> bool:
    return value == expected or isinstance(expected, str) and value == f"sha256:{expected}"


def staged_bytes_digest(root: Path) -> str:
    files: dict[str, bytes] = {}
    for name, value in campaign_tree_files(root, skip=("cells/*/tasks/*/environment/repo/*", "cells/*/request.json", "cells/*/result.json", "cells/*/results/*", "cells/*/runs/*")).items():
        parts = name.split("/")
        if parts[0] in {"context", "packages"} or name == "bin/harbor":
            files[name] = value
        elif parts[0] == "cells" and len(parts) > 1:
            relative = "/".join(parts[2:])
            if parts[1] == "harbor_agents" or (relative not in {"request.json", "result.json"} and not relative.startswith("results/")):
                if not (len(parts) >= 6 and parts[2] == "tasks" and parts[4:6] == ["environment", "repo"]):
                    files[name] = value
    return digest([(name, bytes_digest(value)) for name, value in sorted(files.items())])


def _receipt_rows(root: Path, cell: Cell) -> list[tuple[dict[str, object], int | None]]:
    db = confined_path(root, "runs", "campaign.sqlite")
    if not db.is_file():
        return []
    with sqlite3.connect(db) as connection:
        tables = {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"harness_census_receipts", "runner_exchange_records"}.issubset(tables):
            return []
        trusted_sql = ", r.trusted" if "run_records" in tables else ", NULL"
        rows = connection.execute(
            "SELECT c.receipt_json, c.crucible_run_id, c.trial_id, c.cell_run_id, e.exchange_id"
            + trusted_sql
            + " FROM harness_census_receipts c "
            "JOIN runner_exchange_records e ON e.record_id = c.exchange_record_id "
            + ("LEFT JOIN run_records r ON r.run_id = c.cell_run_id " if "run_records" in tables else "")
            + "WHERE c.campaign_id = ? AND c.cell_run_id = ?",
            (CAMPAIGN_ID, cell.cell_run_id),
        ).fetchall()
    parsed: list[tuple[dict[str, object], int | None]] = []
    for raw, database_run_id, database_trial_id, database_cell_run_id, exchange_id, trusted in rows:
        try:
            receipt = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            fail(f"resume receipt is not valid JSON: {cell.cell_id}")
        if not isinstance(receipt, dict):
            fail(f"resume receipt is not an object: {cell.cell_id}")
        task_id = receipt.get("task_id") or receipt.get("task_name")
        expected_run = f"{CAMPAIGN_ID}--{cell.cell_id}--{task_id}"
        expected_trial = f"{cell.cell_id}--{task_id}"
        expected_exchange = f"{expected_run}--{task_id}"
        if not isinstance(task_id, str) or (database_run_id, database_trial_id, database_cell_run_id, exchange_id) != (expected_run, expected_trial, cell.cell_run_id, expected_exchange):
            fail(f"resume database receipt identity mismatch: {cell.cell_id}")
        parsed.append((receipt, trusted))
    return parsed


def _receipt_identity(receipt: dict[str, object], cell: Cell, stage_digest: str, task_id: str) -> bool:
    def ref(value: object, expected: str) -> bool:
        return _matches_ref(value, expected)

    expected = {
        "campaign_id": CAMPAIGN_ID,
        "cell_id": cell.cell_id,
        "cell_run_id": cell.cell_run_id,
        "task_set_size": cell.task_set_size,
        "task_name": task_id,
        "task_id": task_id,
        "trial_id": f"{cell.cell_id}--{task_id}",
        "crucible_run_id": f"{CAMPAIGN_ID}--{cell.cell_id}--{task_id}",
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            return False
    return (
        receipt.get("schema_version") == "harness_census.trial_receipt.v1"
        and ref(receipt.get("stage_manifest_digest"), stage_digest)
        and ref(receipt.get("task_set_digest"), cell.task_set_digest)
        and ref(receipt.get("retry_policy_digest"), cell.retry_policy_digest)
        and ref(receipt.get("agent_kwargs_base_digest"), cell.agent_kwargs_base_digest)
        and receipt.get("trial_status") in {"success", "quality_failure", "reliability_failure"}
    )


def _parse_content_ref(value: object, label: str) -> tuple[str, str]:
    if not isinstance(value, str):
        fail(f"resume {label} is missing")
    digest_part, separator, relative = value.partition("@")
    if not separator or not digest_part.startswith("sha256:") or not _valid_digest(digest_part.removeprefix("sha256:")):
        fail(f"resume {label} is not a canonical content reference: {value}")
    parts = relative.split("/")
    if any(not part or part in {".", ".."} or "\\" in part or ":" in part for part in parts):
        fail(f"resume {label} has an unsafe content path: {value}")
    return digest_part.removeprefix("sha256:"), relative


def _verify_content_ref(root: Path, value: object, label: str) -> Path:
    expected, relative = _parse_content_ref(value, label)
    path = confined_path(root, *relative.split("/"))
    try:
        actual = bytes_digest(path.read_bytes())
    except OSError as error:
        fail(f"resume {label} content is unreadable: {relative}: {error}")
    if actual != expected:
        fail(f"resume {label} content digest mismatch: {relative}")
    return path


def _receipt_attestation(root: Path, cell: Cell, record: TaskRecord, receipt: dict[str, object]) -> tuple[dict[str, object], str]:
    task_exchange = confined_path(root, "exchange", cell.cell_id, record.task_id)
    result_path = _verify_content_ref(root, receipt.get("runner_exchange_result_ref") or receipt.get("result_ref"), "runner-exchange result")
    if result_path != task_exchange / "result.json":
        fail(f"resume runner-exchange result reference mismatch: {cell.cell_id} {record.task_id}")
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        fail(f"resume runner-exchange result is invalid: {cell.cell_id} {record.task_id}: {error}")
    evidence = result.get("evidence") if isinstance(result, dict) else None
    matches = [item for item in evidence if isinstance(item, dict) and item.get("kind") == "attestation"] if isinstance(evidence, list) else []
    if len(matches) != 1:
        fail(f"resume runner-exchange attestation evidence must contain exactly one item: {cell.cell_id} {record.task_id}")
    item = matches[0]
    relative = item.get("path")
    expected_prefix = f"cells/{cell.cell_id}/results/harbor-jobs/{record.task_id}/"
    if not isinstance(relative, str) or not relative.startswith(expected_prefix):
        fail(f"resume attestation path is outside the current task result directory: {cell.cell_id} {record.task_id}")
    raw_digest = item.get("sha256")
    if isinstance(raw_digest, str) and raw_digest.startswith("sha256:"):
        raw_digest = raw_digest.removeprefix("sha256:")
    if not _valid_digest(raw_digest):
        fail(f"resume attestation evidence digest is invalid: {cell.cell_id} {record.task_id}")
    attestation_path = _verify_content_ref(root, f"sha256:{raw_digest}@{relative}", "attestation evidence")
    attestation_ref = f"sha256:{raw_digest}@{relative}"
    evidence_refs = receipt.get("evidence_refs")
    if not isinstance(evidence_refs, list) or attestation_ref not in evidence_refs:
        fail(f"resume attestation evidence reference is not bound to the receipt: {cell.cell_id} {record.task_id}")
    try:
        attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        fail(f"resume attestation is invalid: {cell.cell_id} {record.task_id}: {error}")
    if not isinstance(attestation, dict) or attestation.get("schema_version") != "crucible.adapter_attestation.v1" or attestation.get("adapter") != cell.harness or attestation.get("composition") != cell.composition or attestation.get("version") != cell.harness_version:
        fail(f"resume attestation adapter identity mismatch: {cell.cell_id} {record.task_id}")
    for key, expected in {"harness": cell.harness, "composition": cell.composition, "harness_version": cell.harness_version}.items():
        if receipt.get(key) != expected:
            fail(f"resume receipt {key} is not bound to the attestation: {cell.cell_id} {record.task_id}")
    observed = attestation.get("observed_identities")
    if attestation.get("status") == "passed":
        if not isinstance(observed, list) or len(observed) != 1 or not isinstance(observed[0], str) or not observed[0].strip():
            fail(f"resume attestation observed model identity is invalid: {cell.cell_id} {record.task_id}")
        effort, effort_source = attestation.get("effort"), attestation.get("effort_source")
        if not isinstance(effort, str) or not effort.strip() or not isinstance(effort_source, str) or not effort_source.strip():
            fail(f"resume attestation effort identity is invalid: {cell.cell_id} {record.task_id}")
        required_bindings = {"provider_route_resolved": observed[0], "provider_effort_resolved": effort, "effort_source": effort_source}
        optional_bindings = {"response_model_attestation": observed[0], "response_effort_attestation": effort}
        for key, expected in required_bindings.items():
            if receipt.get(key) != expected:
                fail(f"resume attestation {key} is not bound to the receipt: {cell.cell_id} {record.task_id}")
        for key, expected in optional_bindings.items():
            if receipt.get(key) is not None and receipt[key] != expected:
                fail(f"resume attestation {key} is not bound to the receipt: {cell.cell_id} {record.task_id}")
    return attestation, relative


def _verify_quality_receipt(root: Path, cell: Cell, record: TaskRecord, receipt: dict[str, object], status: object, task_exchange: Path) -> dict[str, str] | None:
    grader_path = task_exchange / "grader.json"
    if not grader_path.is_file():
        fail(f"resume quality receipt is missing grader artifact: {cell.cell_id} {record.task_id}")
    try:
        grader = json.loads(grader_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"resume grader artifact is invalid: {cell.cell_id} {record.task_id}: {error}")
    grader_bindings = {
        "row_id": cell.row_id,
        "cohort_id": cell.cohort_id,
        "profile_digest": cell.profile_digest,
    }
    if cell.cell_kind == "controlled":
        grader_bindings["baseline_id"] = cell.baseline_id
    task_points = grader.get("task_points") if isinstance(grader, dict) else None
    if not isinstance(grader, dict) or grader.get("schema_version") != "harness_census.grader_receipt.v1" or grader.get("campaign_id") != CAMPAIGN_ID or grader.get("task_id") != record.task_id or grader.get("trial_id") != f"{cell.cell_id}--{record.task_id}" or any(not _matches_ref(grader.get(key), expected) for key, expected in grader_bindings.items()) or not _matches_ref(grader.get("grader_digest"), record.grader_digest) or grader.get("grader_identity") != "harness_census_deterministic" or not isinstance(grader.get("hard_pass"), bool) or isinstance(task_points, bool) or not isinstance(task_points, (int, float)) or not 0.0 <= float(task_points) <= 1.0:
        fail(f"resume grader artifact identity mismatch: {cell.cell_id} {record.task_id}")
    grader_ref = receipt.get("grader_receipt_ref")
    if grader_ref is not None and _verify_content_ref(root, grader_ref, "grader_receipt_ref") != grader_path:
        fail(f"resume grader receipt reference mismatch: {cell.cell_id} {record.task_id}")
    expected_hard_pass = status == "success"
    if grader["hard_pass"] != expected_hard_pass or receipt.get("hard_pass") != expected_hard_pass or receipt.get("task_points") != task_points:
        fail(f"resume receipt score disagrees with grader: {cell.cell_id} {record.task_id}")
    attestation, _ = _receipt_attestation(root, cell, record, receipt)
    tool_manifest = attestation.get("tool_manifest_digest")
    config_digest = attestation.get("config_digest")
    receipt_tool = receipt.get("tool_manifest_digest")
    if isinstance(tool_manifest, str) and tool_manifest and not _matches_ref(receipt_tool, tool_manifest):
        fail(f"resume receipt tool manifest mismatch: {cell.cell_id} {record.task_id}")
    if isinstance(receipt_tool, str) and receipt_tool and not _valid_digest(receipt_tool.removeprefix("sha256:")):
        fail(f"resume receipt tool manifest is invalid: {cell.cell_id} {record.task_id}")
    if not isinstance(config_digest, str) or not isinstance(tool_manifest, str) or not config_digest or not tool_manifest:
        return None
    expected_system = cell.observed_system_identity(config_digest, tool_manifest)
    if receipt.get("system_identity") not in {expected_system, f"sha256:{expected_system}"}:
        fail(f"resume receipt system identity mismatch: {cell.cell_id} {record.task_id}")
    if cell.cell_kind != "native_default":
        return None
    route = receipt.get("provider_route_resolved")
    effort = receipt.get("provider_effort_resolved")
    effort_source = receipt.get("effort_source")
    if not all(isinstance(value, str) and value.strip() for value in (route, effort, effort_source)):
        fail(f"resume native receipt identity is incomplete: {cell.cell_id} {record.task_id}")
    observation = {"model": str(route), "effort": str(effort), "effort_source": str(effort_source), "tool": tool_manifest, "config": config_digest}
    resolved = cell.resolve_native(str(route), str(effort), str(effort_source), tool_manifest, config_digest)
    if not _matches_ref(grader.get("baseline_id"), resolved.baseline_id) or not _matches_ref(receipt.get("baseline_id"), resolved.baseline_id):
        fail(f"resume native baseline identity mismatch: {cell.cell_id} {record.task_id}")
    return observation


def _verify_reliability_receipt(root: Path, cell: Cell, record: TaskRecord, receipt: dict[str, object], result: dict[str, object], trial: dict[str, object], evidence_refs: list[object]) -> None:
    failure_identity: dict[str, str] = {}
    for key in ("failure_class", "failure_stage", "failure_code"):
        value = receipt.get(key)
        if not isinstance(value, str) or not value:
            fail(f"resume reliability receipt is missing {key}: {cell.cell_id} {record.task_id}")
        failure_identity[key] = value
        if trial.get(key) != value:
            fail(f"resume reliability trial disagrees on {key}: {cell.cell_id} {record.task_id}")
    failure_code = failure_identity["failure_code"]
    if failure_code not in SUPPORTED_RELIABILITY_CODES:
        fail(f"resume reliability receipt has unsupported failure_code: {cell.cell_id} {record.task_id}")
    if tuple(failure_identity[key] for key in ("failure_class", "failure_stage", "failure_code")) != reliability_failure_identity(failure_code):
        fail(f"resume reliability receipt has inconsistent failure identity: {cell.cell_id} {record.task_id}")
    expected_status = "timeout" if failure_identity["failure_class"] == "timeout" else "execution_error"
    failure_detail = trial.get("failure_detail")
    if not isinstance(failure_detail, dict) or not failure_detail:
        fail(f"resume reliability trial has invalid failure_detail: {cell.cell_id} {record.task_id}")
    error = result.get("error")
    expected_retryable = failure_code in RETRYABLE_RELIABILITY_CODES
    if result.get("status") != expected_status or not isinstance(error, dict) or error.get("code") != failure_code or error.get("retryable") is not expected_retryable or error.get("detail") != failure_detail:
        fail(f"resume reliability result disagrees with the receipt: {cell.cell_id} {record.task_id}")
    if receipt.get("hard_pass") is not None or receipt.get("task_points") is not None:
        fail(f"resume reliability receipt contains a score: {cell.cell_id} {record.task_id}")
    detail_ref = receipt.get("failure_detail_ref")
    if not isinstance(detail_ref, str) or detail_ref not in evidence_refs:
        fail(f"resume reliability receipt has invalid failure_detail_ref: {cell.cell_id} {record.task_id}")
    detail_path = _verify_content_ref(root, detail_ref, "failure_detail_ref")
    failure_root = confined_path(root, "cells", cell.cell_id, "results", "harbor-jobs", record.task_id)
    if detail_path.name != "result.json" or not detail_path.is_relative_to(failure_root):
        fail(f"resume reliability failure detail is outside the task result: {cell.cell_id} {record.task_id}")


def _verified_task_receipt(root: Path, cell: Cell, record: TaskRecord, stage_digest: str, receipt: dict[str, object], trusted: int | None) -> tuple[bool, dict[str, str] | None]:
    if not _receipt_identity(receipt, cell, stage_digest, record.task_id):
        fail(f"resume receipt identity mismatch: {cell.cell_id} {record.task_id}")
    status = receipt.get("trial_status")
    reliability = status == "reliability_failure"
    required_identity = {
        "cell_kind": cell.cell_kind,
        "composition": cell.composition,
        "harness": cell.harness,
        "harness_version": cell.harness_version,
    }
    if cell.cell_kind == "controlled":
        required_identity.update({
            "model_requested": cell.model_requested,
            "effort_requested": cell.effort_requested,
            "provider_route_resolved": cell.provider_route_resolved,
            "provider_effort_resolved": cell.provider_effort_resolved,
        })
    for key, expected_value in required_identity.items():
        if key not in receipt or receipt[key] != expected_value:
            fail(f"resume receipt cell identity mismatch: {cell.cell_id} {key}")
    if cell.cell_kind == "native_default":
        for key in ("model_requested", "effort_requested"):
            if key in receipt and receipt[key] is not None:
                fail(f"resume native receipt identity mismatch: {cell.cell_id} {key}")
        for key in ("provider_route_resolved", "provider_effort_resolved"):
            if key in receipt and (not isinstance(receipt[key], str) or not receipt[key].strip()):
                fail(f"resume native receipt identity is incomplete: {cell.cell_id} {key}")
    for key, expected_value in {"composition_digest": cell.composition_digest, "adapter_digest": cell.adapter_digest, "mcp_digest": mcp_identity_digest(), "agent_kwargs_digest": agent_kwargs_identity_digest(cell.agent_kwargs), "agent_allowed_hosts_digest": agent_allowed_hosts_identity_digest(cell)}.items():
        if key in receipt and not _matches_ref(receipt[key], expected_value):
            fail(f"resume receipt digest identity mismatch: {cell.cell_id} {key}")
    for key, expected_value in {"gateway_digests": list(cell.gateway_digests), "gateway_dockerfile_digests": list(cell.gateway_dockerfile_digests), "compose_digests": list(cell.compose_digests)}.items():
        if key in receipt and receipt[key] != expected_value:
            fail(f"resume receipt enforcement identity mismatch: {cell.cell_id} {key}")
    for key, expected_value in {"context_manifest_digest": record.context_manifest_digest, "context_pack_digest": record.context_pack_digest}.items():
        if not _matches_ref(receipt.get(key), expected_value):
            fail(f"resume receipt context identity mismatch: {cell.cell_id} {record.task_id} {key}")
    if receipt.get("source_cluster") not in {None, record.source_cluster}:
        fail(f"resume receipt source identity mismatch: {cell.cell_id} {record.task_id}")
    for key, expected_value, label in (("task_digest", record.task_digest, "task digest"), ("comparison_task_digest", record.comparison_task_digest, "comparison identity"), ("context_digest", record.context_digest, "context digest"), ("skill_digest", record.skill_digest, "skill digest")):
        if not _matches_ref(receipt.get(key), expected_value):
            fail(f"resume receipt {label} mismatch: {cell.cell_id} {record.task_id}")
    required_trial_identity = [("profile_digest", cell.profile_digest, "profile")]
    if cell.cell_kind == "controlled":
        required_trial_identity.extend((("row_id", cell.row_id, "row"), ("cohort_id", cell.cohort_id, "cohort")))
    for key, expected_value, label in required_trial_identity:
        if not _matches_ref(receipt.get(key), expected_value):
            fail(f"resume receipt {label} identity mismatch: {cell.cell_id}")
    if cell.cell_kind == "native_default":
        for key, expected_value, label in (("row_id", cell.row_id, "row"), ("cohort_id", cell.cohort_id, "cohort")):
            if receipt.get(key) is not None and not _matches_ref(receipt[key], expected_value):
                fail(f"resume receipt {label} identity mismatch: {cell.cell_id}")
    if trusted is None and not reliability:
        fail(f"resume quality receipt trust is unavailable: {cell.cell_id} {record.task_id}")
    if trusted is not None and int(trusted) != 1 and not (int(trusted) == 0 and reliability):
        fail(f"resume receipt trust is invalid: {cell.cell_id} {record.task_id}")
    task_exchange = confined_path(root, "exchange", cell.cell_id, record.task_id)
    allowed_names = {"request.json", "result.json", "trial.json", "grader.json"}
    names = {path.name for path in task_exchange.iterdir()} if task_exchange.is_dir() else set()
    if not names.issubset(allowed_names):
        fail(f"resume exchange contains conflicting artifacts: {cell.cell_id} {record.task_id}")
    for key in ("runner_exchange_request_ref", "runner_exchange_result_ref"):
        reference = receipt.get(key)
        if reference is not None:
            _verify_content_ref(root, reference, key)
    for key, name in (("request_ref", "request.json"), ("result_ref", "result.json")):
        reference = receipt.get(key)
        if reference is not None:
            path = task_exchange / name
            if not path.is_file() or reference != f"sha256:{bytes_digest(path.read_bytes())}@{path.relative_to(root).as_posix()}":
                fail(f"resume canonical reference mismatch: {cell.cell_id} {record.task_id} {key}")
    for name in ("request.json", "result.json", "trial.json"):
        if not (task_exchange / name).is_file():
            fail(f"resume receipt artifacts are incomplete: {cell.cell_id} {record.task_id}")
    try:
        request = json.loads((task_exchange / "request.json").read_text(encoding="utf-8"))
        result = json.loads((task_exchange / "result.json").read_text(encoding="utf-8"))
        trial = json.loads((task_exchange / "trial.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"resume exchange artifact is invalid: {cell.cell_id} {record.task_id}: {error}")
    expected_run = f"{CAMPAIGN_ID}--{cell.cell_id}--{record.task_id}"
    expected_exchange = f"{expected_run}--{record.task_id}"
    if not isinstance(request, dict) or request.get("schema_version") != "crucible.runner_exchange_request.v1" or request.get("task_id") != record.task_id or request.get("cell_id") != cell.cell_id or request.get("cell_run_id") != cell.cell_run_id or request.get("exchange_id") != expected_exchange:
        fail(f"resume request artifact identity mismatch: {cell.cell_id} {record.task_id}")
    if not isinstance(result, dict) or result.get("schema_version") != "crucible.runner_exchange_result.v1" or result.get("exchange_id") != expected_exchange or result.get("cell_id") != cell.cell_id or result.get("cell_run_id") != cell.cell_run_id:
        fail(f"resume result artifact identity mismatch: {cell.cell_id} {record.task_id}")
    if not isinstance(trial, dict) or trial.get("schema_version") != "harness_census.trial_receipt.v1" or trial.get("campaign_id") != CAMPAIGN_ID or trial.get("crucible_run_id") != expected_run or trial.get("cell_id") != cell.cell_id or trial.get("cell_run_id") != cell.cell_run_id or trial.get("task_id") != record.task_id or trial.get("task_name") != record.task_id or trial.get("trial_id") != f"{cell.cell_id}--{record.task_id}":
        fail(f"resume trial artifact identity mismatch: {cell.cell_id} {record.task_id}")
    trial_path = task_exchange / "trial.json"
    trial_ref = f"sha256:{bytes_digest(trial_path.read_bytes())}@{trial_path.relative_to(root).as_posix()}"
    evidence_refs = receipt.get("evidence_refs")
    if not isinstance(evidence_refs, list) or trial_ref not in evidence_refs:
        fail(f"resume trial artifact is not bound to the receipt: {cell.cell_id} {record.task_id}")
    singular_digests = {"dockerfile_digest": record.dockerfile_digest, "gateway_digest": record.gateway_digest, "gateway_dockerfile_digest": record.gateway_dockerfile_digest, "compose_digest": record.compose_digest}
    for artifact_name, artifact in (("request", request), ("result", result), ("trial", trial)):
        if any(not _matches_ref(artifact.get(key), expected) for key, expected in singular_digests.items()):
            fail(f"resume {artifact_name} task artifact identity mismatch: {cell.cell_id} {record.task_id}")
    if trial.get("trial_status") != status:
        fail(f"resume trial status disagrees with the receipt: {cell.cell_id} {record.task_id}")
    if cell.cell_kind == "controlled":
        if not isinstance(cell.model_requested, str):
            fail(f"resume controlled model identity is missing: {cell.cell_id}")
        provider, separator, model_name = cell.model_requested.partition("/")
        expected_model = {"provider": provider, "name": model_name}
        if not separator:
            fail(f"resume controlled model identity is invalid: {cell.cell_id}")
        for artifact_name, artifact in (("request", request), ("result", result)):
            candidate = artifact.get("candidate")
            if not isinstance(candidate, dict) or candidate.get("model") != expected_model or candidate.get("reasoning_effort") != cell.effort_requested:
                fail(f"resume {artifact_name} treatment identity mismatch: {cell.cell_id} {record.task_id}")
        trial_treatment = {
            "model_requested": cell.model_requested,
            "effort_requested": cell.effort_requested,
            "provider_route_resolved": cell.provider_route_resolved,
            "provider_effort_resolved": cell.provider_effort_resolved,
        }
        if any(trial.get(key) != value for key, value in trial_treatment.items()):
            fail(f"resume trial treatment identity mismatch: {cell.cell_id} {record.task_id}")
    observation: dict[str, str] | None = None
    if reliability:
        _verify_reliability_receipt(root, cell, record, receipt, result, trial, evidence_refs)
        observation = None
    else:
        observation = _verify_quality_receipt(root, cell, record, receipt, status, task_exchange)
    transcript_ref = receipt.get("transcript_ref")
    if transcript_ref is not None:
        _verify_content_ref(root, transcript_ref, "transcript_ref")
    for value in evidence_refs:
        _verify_content_ref(root, value, "evidence ref")
    return reliability, observation


def _derive_cell_result(root: Path, cell: Cell, stage_digest: str, by_task: dict[str, tuple[dict[str, object], int | None]], resolved: Cell | None) -> dict[str, object]:
    cell_dir_prefix = f"cells/{cell.cell_id}/"
    observed_models: list[str] = []
    observed_efforts: list[str] = []
    observed_tools: list[str] = []
    observed_configs: list[str] = []
    observed_systems: list[str] = []
    attestations: list[dict[str, object]] = []
    attestation_digests: list[str] = []
    compact_receipts: list[dict[str, object]] = []
    for record in cell.task_records:
        receipt, _ = by_task[record.task_id]
        attestation, attestation_path = _receipt_attestation(root, cell, record, receipt)
        tool_manifest = attestation.get("tool_manifest_digest")
        config_digest = attestation.get("config_digest")
        if isinstance(tool_manifest, str) and tool_manifest:
            observed_tools.append(tool_manifest)
        if isinstance(config_digest, str) and config_digest:
            observed_configs.append(config_digest)
            if isinstance(tool_manifest, str) and tool_manifest:
                observed_systems.append(cell.observed_system_identity(config_digest, tool_manifest))
        observed = attestation.get("observed_identities")
        model = observed[0] if isinstance(observed, list) and len(observed) == 1 and isinstance(observed[0], str) else None
        if isinstance(model, str) and model:
            observed_models.append(model)
        effort = attestation.get("effort")
        if isinstance(effort, str) and effort:
            observed_efforts.append(effort)
        transcript_ref = receipt.get("transcript_ref")
        if isinstance(transcript_ref, str) and transcript_ref:
            transcript_cell_ref = transcript_ref.split("@", 1)[1].removeprefix(cell_dir_prefix)
        else:
            transcript_cell_ref = None
        attestation_ref = attestation_path.removeprefix(cell_dir_prefix)
        attestation_path_obj = confined_path(root, *attestation_path.split("/"))
        attestations.append({"task_id": record.task_id, "attestation_ref": attestation_ref, "attestation_digest": bytes_digest(attestation_path_obj.read_bytes()), "transcript_ref": transcript_cell_ref, "record": attestation})
        attestation_digests.append(attestations[-1]["attestation_digest"])
        compact_receipts.append(compact_receipt(receipt))
    summary_cell = resolved if resolved is not None else cell
    return {"schema_version": "harness_census.normalized_result.v1", "campaign_id": CAMPAIGN_ID, "cell_id": cell.cell_id, "cell_run_id": cell.cell_run_id, "task_set_digest": cell.task_set_digest, "task_set_size": cell.task_set_size, "retry_policy_digest": cell.retry_policy_digest, "agent_kwargs_base_digest": cell.agent_kwargs_base_digest, "stage_manifest_digest": stage_digest, "return_code": None, "reconstructed": True, "model_requested": cell.model_requested, "effort_requested": cell.effort_requested, "provider_route_resolved": summary_cell.provider_route_resolved, "provider_effort_resolved": summary_cell.provider_effort_resolved, "response_model": observed_models[0] if len(observed_models) == 1 else None, "observed_models": sorted(set(observed_models)), "response_effort": observed_efforts[0] if len(observed_efforts) == 1 else None, "observed_efforts": sorted(set(observed_efforts)), "observed_tool_manifest_digests": sorted(set(observed_tools)), "observed_config_digests": sorted(set(observed_configs)), "observed_system_identities": sorted(set(observed_systems)), "effort_source": summary_cell.effort_source, "network_mode": cell.network_mode, "transport_network_mode": cell.transport_network_mode, "network_enforcement": cell.network_enforcement, "task_network_enforcement": cell.task_network_enforcement, "row_id": cell.row_id, "cohort_id": cell.cohort_id, "baseline_id": summary_cell.baseline_id, "profile_digest": cell.profile_digest, "agent_kwargs": dict(cell.agent_kwargs), "agent_allowed_hosts": list(cell.agent_allowed_hosts), "attestations": attestations, "attestation_digests": sorted(attestation_digests), "runner_exchange_receipts": compact_receipts}


def _reconcile_cell_result(root: Path, cell: Cell, stage_digest: str, by_task: dict[str, tuple[dict[str, object], int | None]], resolved: Cell | None) -> None:
    expected = _derive_cell_result(root, cell, stage_digest, by_task, resolved)
    result_path = confined_path(root, "cells", cell.cell_id, "result.json")
    if not result_path.is_file():
        write_json(result_path, expected)
        return
    try:
        stored = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"resume completed cell result is invalid: {cell.cell_id}: {error}")
    if not isinstance(stored, dict) or stored.get("cell_id") != cell.cell_id or stored.get("stage_manifest_digest") != stage_digest or stored.get("task_set_digest") != cell.task_set_digest:
        fail(f"resume completed cell result identity mismatch: {cell.cell_id}")
    derivable = {"schema_version", "campaign_id", "cell_id", "cell_run_id", "task_set_digest", "task_set_size", "retry_policy_digest", "agent_kwargs_base_digest", "stage_manifest_digest", "model_requested", "effort_requested", "provider_route_resolved", "provider_effort_resolved", "response_model", "observed_models", "response_effort", "observed_efforts", "observed_tool_manifest_digests", "observed_config_digests", "observed_system_identities", "effort_source", "network_mode", "transport_network_mode", "network_enforcement", "task_network_enforcement", "row_id", "cohort_id", "baseline_id", "profile_digest", "agent_kwargs", "agent_allowed_hosts", "attestations", "attestation_digests", "runner_exchange_receipts"}
    if {key: stored.get(key) for key in derivable} != {key: expected.get(key) for key in derivable}:
        fail(f"resume completed cell result is stale or mismatched: {cell.cell_id}")

def resolve_native_observation(cell: Cell, observations: list[dict[str, str]]) -> tuple[Cell, dict[str, str]] | None:
    if cell.cell_kind != "native_default" or len(observations) != len(cell.task_records):
        return None
    if len({tuple(sorted(observation.items())) for observation in observations}) != 1:
        fail(f"native receipts disagree on observed identity: {cell.cell_id}")
    observation = observations[0]
    resolved = cell.resolve_native(observation["model"], observation["effort"], observation["effort_source"], observation["tool"], observation["config"])
    return resolved, observation

def _reconcile_native_baseline(root: Path, cell: Cell, stage_digest: str, resolved: Cell, observation: dict[str, str], by_task: dict[str, tuple[dict[str, object], int | None]]) -> None:
    receipt_digests = [compact_receipt(receipt)["receipt_digest"] for receipt, _ in by_task.values()]
    expected = {
        "schema_version": "harness_census.native_baseline_summary.v1",
        "campaign_id": CAMPAIGN_ID,
        "stage_manifest_digest": stage_digest,
        "cell_id": cell.cell_id,
        "cell_run_id": cell.cell_run_id,
        "baseline_id": resolved.baseline_id,
        "harness": cell.harness,
        "harness_version": cell.harness_version,
        "profile_digest": cell.profile_digest,
        "task_set_digest": cell.task_set_digest,
        "observed_model": observation["model"],
        "observed_effort": observation["effort"],
        "effort_source": observation["effort_source"],
        "tool_manifest_digest": observation["tool"],
        "config_digest": observation["config"],
        "system_identity": cell.observed_system_identity(observation["config"], observation["tool"]),
        "receipt_digests": receipt_digests,
        "status": "valid",
    }
    summary_path = confined_path(root, "baselines", str(resolved.baseline_id), "summary.json")
    if not summary_path.is_file():
        write_json(summary_path, expected)
        return
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        fail(f"resume native baseline summary is invalid: {cell.cell_id}: {error}")
    if not isinstance(summary, dict) or any(summary.get(key) != value for key, value in expected.items() if key != "receipt_digests") or sorted(summary.get("receipt_digests", [])) != sorted(receipt_digests):
        fail(f"resume native baseline summary identity mismatch: {cell.cell_id}")


def cell_receipt_state(root: Path, cell: Cell, stage_digest: str, expected_stage_digest: str | None = None) -> str:
    rows = _receipt_rows(root, cell)
    by_task: dict[str, tuple[dict[str, object], int | None]] = {}
    for receipt, trusted in rows:
        task_id = receipt.get("task_id") or receipt.get("task_name")
        if not isinstance(task_id, str) or task_id in by_task:
            fail(f"resume cell has duplicate or missing receipt task identity: {cell.cell_id}")
        by_task[task_id] = (receipt, trusted)
    expected_tasks = {record.task_id for record in cell.task_records}
    cell_dir = confined_path(root, "cells", cell.cell_id)
    exchange_dir = confined_path(root, "exchange", cell.cell_id)
    if expected_stage_digest is not None and cell_stage_digest(cell_dir, include_workspace=False) != expected_stage_digest:
        fail(f"resume staged bytes changed for cell: {cell.cell_id}")
    runtime_present = (cell_dir / "result.json").is_file() or (cell_dir / "results").is_dir() or exchange_dir.is_dir()
    if not rows and not runtime_present:
        return "absent"
    if not rows:
        return "partial"
    exchange_names = {path.name for path in exchange_dir.iterdir() if path.is_dir()} if exchange_dir.is_dir() else set()
    if not exchange_names.issubset(expected_tasks):
        fail(f"resume cell exchange task set is conflicting: {cell.cell_id}")
    reliability = False
    observations: list[dict[str, str]] = []
    for record in cell.task_records:
        if record.task_id not in by_task:
            continue
        receipt, trusted = by_task[record.task_id]
        task_reliability, observation = _verified_task_receipt(root, cell, record, stage_digest, receipt, trusted)
        reliability = reliability or task_reliability
        if observation is not None:
            observations.append(observation)
    if set(by_task) != expected_tasks or len(rows) != len(expected_tasks):
        return "invalid" if reliability else "partial"
    resolved: Cell | None = None
    if cell.cell_kind == "native_default" and not reliability:
        resolved_observation = resolve_native_observation(cell, observations)
        if resolved_observation is None:
            fail(f"resume native observation is incomplete: {cell.cell_id}")
        resolved, observation = resolved_observation
        for receipt, _ in by_task.values():
            baseline = receipt.get("baseline_id")
            if baseline is not None and baseline not in {resolved.baseline_id, f"sha256:{resolved.baseline_id}"}:
                fail(f"resume native receipt baseline mismatch: {cell.cell_id}")
        _reconcile_native_baseline(root, cell, stage_digest, resolved, observation, by_task)
    _reconcile_cell_result(root, cell, stage_digest, by_task, resolved)
    return "invalid" if reliability else "complete"


def pending_task_ids(root: Path, cell: Cell) -> list[str]:
    rows = _receipt_rows(root, cell)
    verified = {receipt.get("task_id") or receipt.get("task_name") for receipt, _ in rows}
    return [record.task_id for record in cell.task_records if record.task_id not in verified]


def receipt_task_ids(root: Path, cell: Cell) -> list[str]:
    expected = {record.task_id for record in cell.task_records}
    rows = _receipt_rows(root, cell)
    task_ids: list[str] = []
    for receipt, _ in rows:
        task_id = receipt.get("task_id") or receipt.get("task_name")
        if not isinstance(task_id, str) or task_id not in expected or task_id in task_ids:
            fail(f"resume cell has invalid receipt task identity: {cell.cell_id}")
        task_ids.append(task_id)
    return sorted(task_ids)


def verify_pending_task_sources(root: Path, cell: Cell, task_ids: list[str]) -> None:
    tasks = load_tasks()
    for task_id in task_ids:
        record = next((item for item in cell.task_records if item.task_id == task_id), None)
        if record is None:
            fail(f"pending task is undeclared: {cell.cell_id} {task_id}")
        task = tasks[task_id]
        source = confined_path(root, "cells", cell.cell_id, *record.task_dir.split("/"), "environment", "repo")
        observed = task_corpus_identity(task, tree_digest(source, exclude_git=False), file_digest(task.task_dir / "grader.py"), file_digest(task.task_dir / "reference.patch"), reference_hunk_map_digest(task))
        if observed != record.comparison_task_digest:
            fail(f"pending task workspace source identity changed: {cell.cell_id} {task_id}")
