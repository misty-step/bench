"""Run staged cells and persist typed Runner Exchange evidence."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import cast

from harness_census_common import (
    CAMPAIGN_ID, NATIVE_NETWORK_ENFORCEMENT, Cell, Attestation,
    AttestationEntry, ExchangePaths, HarborTrial, Receipt, TaskRecord, bytes_digest,
    digest, fail, load_tasks, write_json,
)

RECEIPT_KEYS = ("run_id", "trial_id", "crucible_run_id", "receipt_id", "exchange_record_id", "trial_status", "failure_code", "request_ref", "result_ref", "grader_receipt_ref", "transcript_ref", "stage_manifest_digest", "row_id", "cohort_id", "baseline_id", "profile_digest")


def model_parts(identity: str) -> dict[str, str]:
    provider, name = identity.split("/", 1)
    return {"provider": provider, "name": name}


def sha256_ref(value: str) -> str:
    return value if value.startswith("sha256:") else f"sha256:{value}"


def cell_task_trial_dir(results: Path, task_id: str) -> Path:
    jobs = results / "harbor-jobs" / task_id / "run"
    candidates = sorted(path for path in jobs.glob("*") if path.is_dir() and (path / "result.json").is_file())
    if len(candidates) != 1:
        fail(f"expected one Harbor trial for {task_id}, found {len(candidates)}")
    return candidates[0]


def collect_attestations(results: Path, cell: Cell) -> list[AttestationEntry]:
    entries: list[AttestationEntry] = []
    native = cell.cell_kind == "native_default"
    for record in cell.task_records:
        trial_dir = cell_task_trial_dir(results, record.task_id)
        matches = sorted(trial_dir.rglob(f"{cell.harness}.attestation.json"))
        if len(matches) != 1:
            fail(f"missing unique adapter attestation for {cell.cell_id} trial {record.task_id}")
        path = matches[0]
        attestation = cast(Attestation, json.loads(path.read_text(encoding="utf-8")))
        status = attestation.get("status")
        if attestation.get("schema_version") != "crucible.adapter_attestation.v1" or status not in {"passed", "failed"}:
            fail(f"adapter attestation is invalid for {cell.cell_id} trial {record.task_id}")
        if attestation.get("adapter") != cell.harness or attestation.get("composition") != cell.composition or attestation.get("version") != cell.harness_version:
            fail(f"adapter attestation identity mismatch for {cell.cell_id} trial {record.task_id}")
        observed = attestation.get("observed_identities")
        if status == "failed" and observed is None:
            observed = []
            attestation["observed_identities"] = observed
        if not isinstance(observed, list) or any(not isinstance(value, str) or not value.strip() for value in observed):
            fail(f"adapter attestation identities are invalid for {cell.cell_id} trial {record.task_id}")
        if status == "passed":
            if len(observed) != 1:
                fail(f"adapter attestation must contain one observed model for {cell.cell_id} trial {record.task_id}")
            expected = observed[0] if native else cell.provider_route_resolved
            expected_effort = attestation.get("effort") if native else cell.provider_effort_resolved
            if native:
                if attestation.get("expected_identity") not in (None, expected) or attestation.get("provider_route") not in (None, expected):
                    fail(f"native adapter attestation identity mismatch for {cell.cell_id} trial {record.task_id}")
                if not isinstance(expected_effort, str) or not expected_effort.strip() or not isinstance(attestation.get("effort_source"), str) or not attestation["effort_source"].strip():
                    fail(f"native adapter attestation effort is incomplete for {cell.cell_id} trial {record.task_id}")
            elif attestation.get("expected_identity") != expected or observed != [expected] or attestation.get("provider_route") != expected or attestation.get("effort") != expected_effort:
                fail(f"adapter attestation expected/observed identity mismatch for {cell.cell_id} trial {record.task_id}")
            if int(attestation.get("fallback_count", -1)) != 0 or int(attestation.get("turn_count", 0)) < 1:
                fail(f"adapter attestation fallback or turn invariant failed for {cell.cell_id} trial {record.task_id}")
        for field in ("tool_manifest_digest", "config_digest"):
            value = attestation.get(field)
            if not isinstance(value, str) or len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                fail(f"adapter attestation {field} is invalid for {cell.cell_id} trial {record.task_id}")
        transcript = path.with_name(f"{cell.harness}.jsonl")
        entries.append({"task_id": record.task_id, "trial_dir": trial_dir, "attestation_path": path, "attestation_ref": path.relative_to(cell.cell_dir).as_posix(), "attestation_digest": bytes_digest(path.read_bytes()), "transcript_ref": transcript.relative_to(cell.cell_dir).as_posix() if transcript.is_file() else None, "transcript_path": transcript if transcript.is_file() else None, "record": attestation})
    return entries


def _failure_text(trial: HarborTrial, attestation: Attestation) -> str:
    exception = trial.get("exception_info")
    values: list[str] = []
    if isinstance(exception, dict):
        values.extend(str(exception.get(field, "")) for field in ("exception_type", "exception_message"))
    elif exception:
        values.append(str(exception))
    values.extend(str(attestation.get(field, "")) for field in ("reason", "error", "message"))
    return " ".join(value for value in values if value).strip()


def _sanitize_failure_text(value: str) -> str:
    value = re.sub(r"(?i)bearer\s+[^\s,;]+", "Bearer <redacted>", value)
    value = re.sub(r"(?i)(?:api[_ -]?key|token|secret|password)\s*[:=]\s*[^\s,;]+", "<redacted>", value)
    value = re.sub(r"\b(?:sk|key|token)-[A-Za-z0-9_-]{12,}", "<redacted>", value)
    return " ".join(value.split())[:512]


def classify_reliability(trial: HarborTrial, attestation: Attestation, transcript_path: Path | None) -> tuple[str, str, str] | None:
    exception = trial.get("exception_info")
    exception_type = str(exception.get("exception_type", "") if isinstance(exception, dict) else "")
    reason = attestation.get("reason") if isinstance(attestation.get("reason"), str) else ""
    failed = bool(trial.get("exception_info")) or attestation.get("status") == "failed"
    provider_reasons = {"provider_error": "provider_request_failed", "provider_rate_limited": "provider_rate_limited", "provider_authentication_failed": "provider_authentication_failed", "provider_budget_exceeded": "provider_budget_exceeded"}
    provider_exceptions = {"AuthenticationError": "provider_authentication_failed", "RateLimitError": "provider_rate_limited", "BudgetExceededError": "provider_budget_exceeded", "ProviderError": "provider_request_failed"}
    if reason in provider_reasons:
        return "provider", "run", provider_reasons[reason]
    if exception_type in provider_exceptions:
        return "provider", "run", provider_exceptions[exception_type]
    if transcript_path is None or not transcript_path.is_file():
        return "transcript", "collect", "transcript_missing"
    if not failed:
        return None
    if reason == "verifier_reward_missing":
        return "harness", "grade", "verifier_reward_missing"
    if reason == "turn_limit_exceeded":
        return "timeout", "run", "adapter_turn_limit_exceeded"
    if reason == "timeout" or exception_type in {"TimeoutError", "DeadlineExceededError"}:
        return "timeout", "run", "adapter_timeout"
    if reason == "setup_error" or exception_type in {"SetupError", "BootstrapError", "InstallError"}:
        return "harness", "launch", "adapter_setup_failed"
    if reason in {"transport_error", "connection_error"} or exception_type in {"TransportError", "ConnectionError"}:
        return "transport", "run", "transport_request_failed"
    return "harness", "run", "adapter_execution_failed"


def reliability_detail(trial: HarborTrial, attestation: Attestation, failure: tuple[str, str, str]) -> dict[str, object]:
    exception = trial.get("exception_info")
    return {"schema_version": "harness_census.reliability_evidence.v1", "failure_class": failure[0], "failure_stage": failure[1], "failure_code": failure[2], "exception_type": exception.get("exception_type") if isinstance(exception, dict) else None, "exception_message": _sanitize_failure_text(str(exception.get("exception_message", ""))) if isinstance(exception, dict) else None, "attestation_status": attestation.get("status"), "attestation_reason": _sanitize_failure_text(str(attestation.get("reason", ""))) or None}


def trial_timestamp(trial: HarborTrial, field: str) -> str:
    value = trial.get(field)
    if not isinstance(value, str) or not value.strip():
        fail(f"Harbor trial has no {field} runtime timestamp")
    return value


def exchange_envelopes(root: Path, cell: Cell, record: TaskRecord, trial_dir: Path, attestation_entry: AttestationEntry, stage_digest: str) -> ExchangePaths:
    task_id = record.task_id
    generated_grader_path = cell.cell_dir / record.task_dir / "tests" / "verify.py"
    harbor_result_path = trial_dir / "result.json"
    trial_raw = cast(HarborTrial, json.loads(harbor_result_path.read_text(encoding="utf-8")))
    observed_hosts = trial_raw.get("config", {}).get("agent", {}).get("extra_allowed_hosts", [])
    if observed_hosts != list(cell.agent_allowed_hosts):
        fail(f"Harbor agent network allowlist mismatch for {cell.cell_id} {task_id}")
    attestation, transcript = attestation_entry["record"], attestation_entry["transcript_path"]
    failure = classify_reliability(trial_raw, attestation, transcript)
    if failure is None and not generated_grader_path.is_file():
        fail(f"generated hidden verifier is missing: {generated_grader_path}")
    grader_digest = bytes_digest(generated_grader_path.read_bytes()) if generated_grader_path.is_file() else None
    reward_path, report_path = trial_dir / "verifier" / "reward.json", trial_dir / "verifier" / "grader-report.json"
    if failure is None and (not reward_path.is_file() or not report_path.is_file()):
        fail(f"staged Harbor trial did not write numeric reward and grader report: {cell.cell_id} {task_id}")
    reward_raw = json.loads(reward_path.read_text(encoding="utf-8")) if reward_path.is_file() else None
    if failure is None and (isinstance(reward_raw, bool) or not isinstance(reward_raw, (int, float))):
        fail(f"staged Harbor reward.json is not numeric: {cell.cell_id} {task_id}")
    trial_id, run_id = f"{cell.cell_id}--{task_id}", f"{CAMPAIGN_ID}--{cell.cell_id}--{task_id}"
    stage_ref = sha256_ref(stage_digest)
    context_ref = sha256_ref(digest({"composition": cell.composition, "task": task_id}))
    skill_ref = sha256_ref(digest({"harness": cell.harness, "skills": "none"}))
    mcp_ref = sha256_ref(digest({"identity": "none", "tools": [], "network": "denied"}))
    tool_manifest_ref = sha256_ref(str(attestation["tool_manifest_digest"]))
    payload: dict[str, object] = {"trial_id": trial_id, "crucible_run_id": run_id, "cell_id": cell.cell_id, "cell_run_id": cell.cell_run_id, "task_set_digest": sha256_ref(cell.task_set_digest), "task_set_size": cell.task_set_size, "retry_policy_digest": sha256_ref(cell.retry_policy_digest), "agent_kwargs_base_digest": sha256_ref(cell.agent_kwargs_base_digest), "campaign_id": CAMPAIGN_ID, "stage_manifest_digest": stage_ref, "source_cluster": load_tasks()[task_id].source_cluster, "task_digest": sha256_ref(record.task_digest), "cell_kind": cell.cell_kind, "row_id": sha256_ref(cell.row_id) if cell.row_id else None, "cohort_id": sha256_ref(cell.cohort_id) if cell.cohort_id else None, "baseline_id": sha256_ref(cell.baseline_id) if cell.baseline_id else None, "profile_digest": sha256_ref(cell.profile_digest), "composition": cell.composition, "composition_digest": sha256_ref(cell.composition_digest), "network_mode": cell.network_mode, "transport_network_mode": cell.transport_network_mode, "network_enforcement": cell.network_enforcement, "task_network_enforcement": cell.task_network_enforcement, "context_digest": context_ref, "skill_digest": skill_ref, "mcp_digest": mcp_ref, "tool_manifest_digest": tool_manifest_ref, "system_identity": f"{cell.harness}@{cell.harness_version}", "agent_kwargs": dict(cell.agent_kwargs), "agent_allowed_hosts": list(cell.agent_allowed_hosts), "agent_kwargs_digest": sha256_ref(digest(cell.agent_kwargs)), "agent_allowed_hosts_digest": sha256_ref(digest(list(cell.agent_allowed_hosts))), "provider_route_resolved": cell.provider_route_resolved, "provider_effort_resolved": cell.provider_effort_resolved, "response_effort_attestation": attestation.get("effort"), "default_resolution_source": cell.default_resolution_source}
    payload["comparison_task_digest"] = sha256_ref(record.comparison_task_digest)
    payload = {key: value for key, value in payload.items() if value is not None}
    if failure is not None:
        payload.update({"failure_class": failure[0], "failure_stage": failure[1], "failure_code": failure[2], "failure_detail_ref": f"sha256:{bytes_digest(harbor_result_path.read_bytes())}@{harbor_result_path.relative_to(root).as_posix()}"})
    if cell.cell_kind == "native_default":
        payload["effort_source"] = cell.effort_source
    cell_prefix = f"cells/{cell.cell_id}"
    workspace_path = f"{cell_prefix}/{record.task_dir}/environment/repo"
    instruction_path = f"{cell_prefix}/{record.task_dir}/instruction.md"
    model_requested, effort_requested = cell.model_requested, cell.effort_requested
    candidate = {"kind": "agent", "harness": cell.harness, "harness_version": cell.harness_version, "model": model_parts(model_requested) if model_requested is not None else None, "reasoning_effort": effort_requested, "toolset_hash": tool_manifest_ref}
    authority_network = "allowlist" if cell.network_enforcement == NATIVE_NETWORK_ENFORCEMENT else "deny"
    authority_hosts = list(cell.agent_allowed_hosts) if authority_network == "allowlist" else []
    request = {"schema_version": "crucible.runner_exchange_request.v1", "exchange_id": f"{run_id}--{task_id}", "task_id": task_id, "cell_id": cell.cell_id, "cell_run_id": cell.cell_run_id, "task_set_digest": sha256_ref(cell.task_set_digest), "task_set_size": cell.task_set_size, "retry_policy_digest": sha256_ref(cell.retry_policy_digest), "agent_kwargs_base_digest": sha256_ref(cell.agent_kwargs_base_digest), "adapter": {"name": f"crucible.harbor_agents.{cell.harness}", "version": cell.harness_version, "digest": sha256_ref(cell.adapter_digest)}, "candidate": candidate, "capabilities": ["workspace_edit", "transcript", "usage"], "input": {"workspace": workspace_path, "instruction": instruction_path, "context": [], "digest": sha256_ref(bytes_digest((root / instruction_path).read_bytes()))}, "authority": {"filesystem_roots": [workspace_path, instruction_path], "network": authority_network, "allowed_hosts": authority_hosts, "credential_refs": []}, "limits": {"timeout_ms": 900000, "max_output_bytes": 1048576, "cpu_millicores": 1000, "memory_mb": 1024, "storage_mb": 2048}, "provenance": {"repo": load_tasks()[task_id].source_repository, "git_sha": load_tasks()[task_id].source_sha, "invocation_id": f"{run_id}--{task_id}"}, "trust": {"required_evidence_kinds": ["final_state", "transcript"], "require_transcript": True, "require_usage": True, "require_cost": False, "require_response_model": model_requested is not None}, "adapter_payload": payload}
    attestation_path = attestation_entry["attestation_path"]
    evidence: list[dict[str, object]] = []
    if failure is None:
        final = trial_dir / "verifier" / "test-stdout.txt"
        if not final.is_file():
            final = reward_path
        if not final.is_file():
            fail(f"required verifier evidence is missing: {final}")
        evidence.append({"kind": "final_state", "path": final.relative_to(root).as_posix(), "sha256": bytes_digest(final.read_bytes()), "media_type": "text/plain"})
    if transcript is not None and transcript.is_file():
        evidence.append({"kind": "transcript", "path": transcript.relative_to(root).as_posix(), "sha256": bytes_digest(transcript.read_bytes()), "media_type": "application/x-ndjson"})
    evidence.append({"kind": "attestation", "path": attestation_path.relative_to(root).as_posix(), "sha256": bytes_digest(attestation_path.read_bytes()), "media_type": "application/json"})
    observed = attestation.get("observed_identities") or []
    result: dict[str, object] = {"schema_version": "crucible.runner_exchange_result.v1", "exchange_id": request["exchange_id"], "cell_id": cell.cell_id, "cell_run_id": cell.cell_run_id, "task_set_digest": sha256_ref(cell.task_set_digest), "task_set_size": cell.task_set_size, "retry_policy_digest": sha256_ref(cell.retry_policy_digest), "agent_kwargs_base_digest": sha256_ref(cell.agent_kwargs_base_digest), "adapter": request["adapter"], "candidate": candidate, "status": "timeout" if failure and failure[2] == "adapter_timeout" else "execution_error" if failure else "success", "evidence": evidence, "usage": {"input_tokens": None, "output_tokens": None, "cache_tokens": None, "cost_usd": None, "latency_ms": max(1, int(float(attestation.get("elapsed_seconds", 0)) * 1000))}, "provenance": {"response_model": observed[0] if observed else None, "started_at": trial_timestamp(trial_raw, "started_at"), "finished_at": trial_timestamp(trial_raw, "finished_at")}, "adapter_payload": payload}
    result["comparison_task_digest"] = sha256_ref(record.comparison_task_digest)
    if failure is None:
        result["output"] = {"summary": "Harbor task completed", "primary_artifact": evidence[0]["path"], "metadata": {"reward": reward_raw, "network_mode": cell.network_mode, "transport_network_mode": cell.transport_network_mode, "network_enforcement": cell.network_enforcement, "task_network_enforcement": cell.task_network_enforcement}}
    else:
        retryable = failure[2] in {"provider_request_failed", "provider_rate_limited", "adapter_timeout", "transport_request_failed"}
        result["error"] = {"code": failure[2], "message": _sanitize_failure_text(_failure_text(trial_raw, attestation)) or "Harbor reliability failure", "retryable": retryable, "detail": reliability_detail(trial_raw, attestation, failure)}
    exchange_dir = root / "exchange" / cell.cell_id / task_id
    exchange_dir.mkdir(parents=True, exist_ok=True)
    request_path, result_path, trial_path, grader_path = exchange_dir / "request.json", exchange_dir / "result.json", exchange_dir / "trial.json", exchange_dir / "grader.json"
    write_json(request_path, request)
    write_json(result_path, result)
    trial_record: dict[str, object] = {"schema_version": "harness_census.trial_receipt.v1", "campaign_id": CAMPAIGN_ID, "trial_id": trial_id, "crucible_run_id": run_id, "cell_id": cell.cell_id, "cell_run_id": cell.cell_run_id, "task_set_digest": sha256_ref(cell.task_set_digest), "task_set_size": cell.task_set_size, "retry_policy_digest": sha256_ref(cell.retry_policy_digest), "agent_kwargs_base_digest": sha256_ref(cell.agent_kwargs_base_digest), "source_cluster": load_tasks()[task_id].source_cluster, "task_name": task_id, "stage_manifest_digest": stage_ref, "network_mode": cell.network_mode, "transport_network_mode": cell.transport_network_mode, "network_enforcement": cell.network_enforcement, "task_network_enforcement": cell.task_network_enforcement, "assistant_turns": trial_raw.get("assistant_turns"), "verifier_result": trial_raw.get("verifier_result")}
    trial_record["comparison_task_digest"] = sha256_ref(record.comparison_task_digest)
    if failure is not None:
        trial_record.update({"trial_status": "reliability_failure", "failure_class": failure[0], "failure_stage": failure[1], "failure_code": failure[2], "failure_detail": reliability_detail(trial_raw, attestation, failure)})
    write_json(trial_path, trial_record)
    if failure is None:
        write_json(grader_path, {"schema_version": "harness_census.grader_receipt.v1", "campaign_id": CAMPAIGN_ID, "trial_id": trial_id, "task_id": task_id, "grader_identity": "harness_census_deterministic", "grader_digest": grader_digest, "hard_pass": reward_raw == 1.0, "task_points": float(reward_raw), "grader_ms": None})
    else:
        grader_path = None
    return ExchangePaths(request_path, result_path, trial_path, grader_path)


def ingest_task(crucible: Path, root: Path, cell: Cell, record: TaskRecord, paths: ExchangePaths, stage_digest: str, tool_manifest_digest: str) -> dict[str, object]:
    db = root / "runs" / "campaign.sqlite"
    db.parent.mkdir(parents=True, exist_ok=True)
    run_id = f"{CAMPAIGN_ID}--{cell.cell_id}--{record.task_id}"
    command = [
        str(crucible),
        "runner-exchange",
        "ingest-harbor",
        "--root",
        str(root),
        "--request",
        str(paths.request),
        "--result",
        str(paths.result),
        "--trial",
        str(paths.trial),
        "--campaign-id", CAMPAIGN_ID,
        "--stage-manifest-digest", sha256_ref(stage_digest),
        "--cell-id", cell.cell_id,
        "--cell-run-id", cell.cell_run_id,
        "--run-id", run_id,
        "--task-set-digest", sha256_ref(cell.task_set_digest),
        "--task-set-size", str(cell.task_set_size),
        "--retry-policy-digest", sha256_ref(cell.retry_policy_digest),
        "--agent-kwargs-base-digest", sha256_ref(cell.agent_kwargs_base_digest),
        "--source-cluster", load_tasks()[record.task_id].source_cluster,
        "--task-digest", sha256_ref(record.task_digest),
        "--comparison-task-digest", sha256_ref(record.comparison_task_digest),
        "--cell-kind", cell.cell_kind,
        "--profile-digest", sha256_ref(cell.profile_digest),
        "--composition", cell.composition,
        "--composition-digest", sha256_ref(cell.composition_digest),
        "--context-digest", sha256_ref(digest({"composition": cell.composition, "task": record.task_id})),
        "--skill-digest", sha256_ref(digest({"harness": cell.harness, "skills": "none"})),
        "--mcp-digest", sha256_ref(digest({"identity": "none", "tools": [], "network": "denied"})),
        "--tool-manifest-digest", sha256_ref(tool_manifest_digest),
    ]
    for option, value in [
        ("--row-id", cell.row_id),
        ("--cohort-id", cell.cohort_id),
        ("--baseline-id", cell.baseline_id),
        ("--default-resolution-source", cell.default_resolution_source),
    ]:
        if value is not None:
            command += [option, sha256_ref(value) if option.endswith("-id") else value]
    if paths.grader is not None:
        command += ["--grader", str(paths.grader)]
    command += ["--db", str(db), "--json"]
    result_run = subprocess.run(command, cwd=root, text=True, capture_output=True, check=False)
    if result_run.returncode:
        fail(f"Runner Exchange ingest failed for {record.task_id}: {_sanitize_failure_text(result_run.stderr[-1000:])}")
    try:
        return cast(dict[str, object], json.loads(result_run.stdout))
    except json.JSONDecodeError as error:
        fail(f"Runner Exchange ingest returned invalid JSON for {record.task_id}: {error}")


def compact_receipt(value: Receipt) -> dict[str, object]:
    compact = {key: value[key] for key in RECEIPT_KEYS if key in value and isinstance(value[key], (str, int, float, bool))}
    compact["receipt_digest"] = digest(compact)
    return compact


def run_cell(root: Path, cell: Cell, crucible: Path, harbor: Path, stage_digest: str) -> None:
    output = cell.cell_dir / "results"
    output.mkdir(exist_ok=True)
    command = [str(crucible), "run", str(cell.spec_path), "--out", str(output), "--json"]
    request = {"schema_version": "harness_census.normalized_request.v1", "campaign_id": CAMPAIGN_ID, "stage_manifest_digest": stage_digest, "cell_id": cell.cell_id, "cell_run_id": cell.cell_run_id, "task_set_digest": cell.task_set_digest, "task_set_size": cell.task_set_size, "retry_policy_digest": cell.retry_policy_digest, "agent_kwargs_base_digest": cell.agent_kwargs_base_digest, "cell_kind": cell.cell_kind, "harness": cell.harness, "harness_version": cell.harness_version, "composition": cell.composition, "model_requested": cell.model_requested, "effort_requested": cell.effort_requested, "default_resolution_source": cell.default_resolution_source, "agent_kwargs": dict(cell.agent_kwargs), "agent_allowed_hosts": authority_hosts, "network_mode": cell.network_mode, "transport_network_mode": cell.transport_network_mode, "network_enforcement": cell.network_enforcement, "task_network_enforcement": cell.task_network_enforcement, "authority": {"network": "allowlist" if authority_hosts else "deny", "allowed_hosts": authority_hosts}, "row_id": cell.row_id, "cohort_id": cell.cohort_id, "baseline_id": cell.baseline_id, "task_digest": cell.task_digest, "composition_digest": cell.composition_digest, "adapter_digest": cell.adapter_digest, "profile_digest": cell.profile_digest}
    request["comparison_task_digests"] = {record.task_id: record.comparison_task_digest for record in cell.task_records}
    write_json(cell.cell_dir / "request.json", request)
    environment = {**os.environ, "PATH": f"{harbor.parent}:{os.environ.get('PATH', '')}"}
    result_run = subprocess.run(command, cwd=cell.cell_dir, env=environment, text=True, capture_output=True, check=False)
    if result_run.returncode:
        fail(f"Crucible failed for {cell.cell_id}: {_sanitize_failure_text(result_run.stderr[-500:])}")
    attestations = collect_attestations(output, cell)
    passed = [entry for entry in attestations if entry["record"].get("status") == "passed"]
    if cell.cell_kind == "native_default" and passed:
        observed_models = sorted({entry["record"]["observed_identities"][0] for entry in passed})
        observed_efforts = sorted({entry["record"]["effort"] for entry in passed})
        effort_sources = sorted({entry["record"]["effort_source"] for entry in passed})
        if len(observed_models) != 1 or len(observed_efforts) != 1 or len(effort_sources) != 1:
            fail(f"native cell observed model, effort, or effort source is not singular: {cell.cell_id}")
        cell = cell.resolve_native(observed_models[0], observed_efforts[0], effort_sources[0])
    receipts: list[dict[str, object]] = []
    for record, attestation in zip(cell.task_records, attestations):
        tool_manifest_digest = str(attestation["record"]["tool_manifest_digest"])
        paths = exchange_envelopes(root, cell, record, attestation["trial_dir"], attestation, stage_digest)
        receipts.append(ingest_task(crucible, root, cell, record, paths, stage_digest, tool_manifest_digest))
    observed = sorted({entry["record"]["observed_identities"][0] for entry in passed if entry["record"].get("observed_identities")})
    observed_efforts = sorted({entry["record"]["effort"] for entry in passed if entry["record"].get("effort")})
    if len(passed) == len(attestations) and (observed != [cell.provider_route_resolved] or observed_efforts != [cell.provider_effort_resolved]):
        fail(f"cell observed model or effort identity is not singular: {cell.cell_id}")
    attestation_receipts = [{"task_id": entry["task_id"], "attestation_ref": entry["attestation_ref"], "attestation_digest": entry["attestation_digest"], "transcript_ref": entry["transcript_ref"], "record": entry["record"]} for entry in attestations]
    write_json(cell.cell_dir / "result.json", {"schema_version": "harness_census.normalized_result.v1", "campaign_id": CAMPAIGN_ID, "cell_id": cell.cell_id, "cell_run_id": cell.cell_run_id, "task_set_digest": cell.task_set_digest, "task_set_size": cell.task_set_size, "retry_policy_digest": cell.retry_policy_digest, "agent_kwargs_base_digest": cell.agent_kwargs_base_digest, "stage_manifest_digest": stage_digest, "return_code": result_run.returncode, "model_requested": cell.model_requested, "effort_requested": cell.effort_requested, "provider_route_resolved": cell.provider_route_resolved, "provider_effort_resolved": cell.provider_effort_resolved, "response_model": observed[0] if len(observed) == 1 else None, "observed_models": observed, "response_effort": observed_efforts[0] if len(observed_efforts) == 1 else None, "observed_efforts": observed_efforts, "network_mode": cell.network_mode, "transport_network_mode": cell.transport_network_mode, "network_enforcement": cell.network_enforcement, "task_network_enforcement": cell.task_network_enforcement, "row_id": cell.row_id, "cohort_id": cell.cohort_id, "baseline_id": cell.baseline_id, "profile_digest": cell.profile_digest, "agent_kwargs": dict(cell.agent_kwargs), "agent_allowed_hosts": list(cell.agent_allowed_hosts), "attestations": attestation_receipts, "attestation_digests": [entry["attestation_digest"] for entry in attestations], "runner_exchange_receipts": [compact_receipt(cast(Receipt, receipt)) for receipt in receipts]})
