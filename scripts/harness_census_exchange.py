"""Run staged cells and persist typed Runner Exchange evidence."""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess
import sys
from typing import cast

from harness_census_common import (
    CAMPAIGN_ID, COMPACT_RECEIPT_KEYS, NATIVE_NETWORK_ENFORCEMENT, Cell, Attestation,
    AttestationEntry, ExchangePaths, HarborTrial, Receipt, TaskRecord, agent_allowed_hosts_identity_digest,
    agent_kwargs_identity_digest, bytes_digest, cell_allowed_hosts, cell_stage_digest, confined_path, digest, fail,
    harbor_reward_value, load_tasks, mcp_identity_digest, write_json,
)


SAFE_RUNTIME_ENV_KEYS = (
    "PATH",
    "DOCKER_HOST",
    "DOCKER_CONTEXT",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TMPDIR",
    "TMP",
    "TEMP",
    "HOME",
)


def safe_runtime_environment(harbor: Path | None = None) -> dict[str, str]:
    environment = {key: value for key in SAFE_RUNTIME_ENV_KEYS if (value := os.environ.get(key)) is not None}
    if harbor is not None:
        existing_path = environment.get("PATH")
        environment["PATH"] = os.pathsep.join(part for part in (str(harbor.parent), existing_path) if part)
    return environment



def model_parts(identity: str) -> dict[str, str]:
    provider, name = identity.split("/", 1)
    return {"provider": provider, "name": name}


def sha256_ref(value: str) -> str:
    return value if value.startswith("sha256:") else f"sha256:{value}"


def cell_task_trial_dir(results: Path, task_id: str, *, materialize_missing: bool = True) -> Path | None:
    jobs = results / "harbor-jobs" / task_id / "run"
    candidates = sorted(path for path in jobs.glob("*") if path.is_dir() and (path / "result.json").is_file())
    if len(candidates) == 1:
        return candidates[0]
    if not materialize_missing:
        return None
    suffix = "missing" if not candidates else f"ambiguous-{len(candidates)}"
    trial_dir = jobs / f"_census-reliability-{suffix}"
    trial_dir.mkdir(parents=True, exist_ok=True)
    result_path = trial_dir / "result.json"
    if not result_path.exists():
        write_json(result_path, {"schema_version": "harness_census.trial_receipt.v1", "task_name": task_id, "exception_info": {"exception_type": "HarborTrialUnavailable", "exception_message": f"expected one Harbor trial, found {len(candidates)}", "reliability_code": "harbor_trial_unavailable", "candidate_paths": [path.as_posix() for path in candidates]}})
    return trial_dir


def collect_attestations(results: Path, cell: Cell, records: list[TaskRecord] | tuple[TaskRecord, ...] | None = None, *, materialize_missing: bool = True) -> list[AttestationEntry]:
    entries: list[AttestationEntry] = []
    native = cell.cell_kind == "native_default"
    for record in records if records is not None else cell.task_records:
        trial_dir = cell_task_trial_dir(results, record.task_id, materialize_missing=materialize_missing)
        if trial_dir is None:
            continue
        matches = sorted(trial_dir.rglob(f"{cell.harness}.attestation.json"))
        original = matches[0] if len(matches) == 1 else None
        path = original or trial_dir / f"{cell.harness}.attestation.reliability.json"
        try:
            attestation = cast(Attestation, json.loads(path.read_text(encoding="utf-8"))) if original else {}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            attestation = {}
        valid = (
            attestation.get("schema_version") == "crucible.adapter_attestation.v1"
            and attestation.get("status") in {"passed", "failed"}
            and attestation.get("adapter") == cell.harness
            and attestation.get("composition") == cell.composition
            and attestation.get("version") == cell.harness_version
        )
        if not valid:
            path = trial_dir / f"{cell.harness}.attestation.reliability.json"
            attestation = {"schema_version": "crucible.adapter_attestation.v1", "adapter": cell.harness, "composition": cell.composition, "version": cell.harness_version, "status": "failed", "observed_identities": [], "reason": "adapter_attestation_missing" if original is None else "adapter_attestation_invalid", "source_attestation_path": original.relative_to(trial_dir).as_posix() if original else None}
            write_json(path, attestation)
        status = attestation.get("status")
        observed = attestation.get("observed_identities")
        if status == "failed" and observed is None:
            observed = []
            attestation["observed_identities"] = observed
        if not isinstance(observed, list) or any(not isinstance(value, str) or not value.strip() for value in observed):
            path = trial_dir / f"{cell.harness}.attestation.reliability.json"
            attestation = {"schema_version": "crucible.adapter_attestation.v1", "adapter": cell.harness, "composition": cell.composition, "version": cell.harness_version, "status": "failed", "observed_identities": [], "reason": "adapter_attestation_invalid"}
            write_json(path, attestation)
            status, observed = "failed", []
        if status == "passed":
            expected = observed[0] if len(observed) == 1 else None
            expected_effort = attestation.get("effort") if native else cell.provider_effort_resolved
            identity_ok = len(observed) == 1
            if native:
                identity_ok = identity_ok and attestation.get("expected_identity") in (None, expected) and attestation.get("provider_route") in (None, expected) and isinstance(expected_effort, str) and bool(expected_effort.strip()) and isinstance(attestation.get("effort_source"), str) and bool(attestation["effort_source"].strip())
            else:
                identity_ok = identity_ok and attestation.get("expected_identity") == cell.provider_route_resolved and expected == cell.provider_route_resolved and attestation.get("provider_route") == cell.provider_route_resolved and attestation.get("effort") == expected_effort
            identity_ok = identity_ok and int(attestation.get("fallback_count", -1)) == 0 and int(attestation.get("turn_count", 0)) >= 1
            for field in ("tool_manifest_digest", "config_digest"):
                value = attestation.get(field)
                identity_ok = identity_ok and isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)
            if not identity_ok:
                path = trial_dir / f"{cell.harness}.attestation.reliability.json"
                attestation = {"schema_version": "crucible.adapter_attestation.v1", "adapter": cell.harness, "composition": cell.composition, "version": cell.harness_version, "status": "failed", "observed_identities": [], "reason": "adapter_attestation_invalid", "source_attestation_path": original.relative_to(trial_dir).as_posix() if original else None}
                write_json(path, attestation)
                status, observed = "failed", []
        transcript = path.with_name(f"{cell.harness}.jsonl")
        entries.append({"task_id": record.task_id, "trial_dir": trial_dir, "attestation_path": path, "attestation_ref": path.relative_to(cell.cell_dir).as_posix(), "attestation_digest": bytes_digest(path.read_bytes()), "transcript_ref": transcript.relative_to(cell.cell_dir).as_posix() if transcript.is_file() else None, "transcript_path": transcript if transcript.is_file() else None, "record": attestation})
    return entries

def native_observation(cell: Cell, attestations: list[AttestationEntry]) -> tuple[Cell, dict[str, str]] | None:
    passed = [entry for entry in attestations if entry["record"].get("status") == "passed"]
    if cell.cell_kind != "native_default" or len(cell.task_records) != 3 or len(passed) != 3:
        return None
    observations: list[tuple[str, str, str, str, str, str]] = []
    for entry in passed:
        record = entry["record"]
        observed = record.get("observed_identities")
        model = observed[0] if isinstance(observed, list) and len(observed) == 1 and isinstance(observed[0], str) else None
        effort = record.get("effort")
        effort_source = record.get("effort_source")
        tool_manifest = record.get("tool_manifest_digest")
        config_digest = record.get("config_digest")
        if not all(isinstance(value, str) and value.strip() for value in (model, effort, effort_source, tool_manifest, config_digest)):
            fail(f"native attestation identity is incomplete: {cell.cell_id} {entry['task_id']}")
        system_identity = cell.observed_system_identity(config_digest, tool_manifest)
        observations.append((model, effort, effort_source, tool_manifest, config_digest, system_identity))
    if len(set(observations)) != 1:
        fail(f"native task attestations disagree on observed identity: {cell.cell_id}")
    model, effort, effort_source, tool_manifest, config_digest, system_identity = observations[0]
    resolved = cell.resolve_native(model, effort, effort_source, tool_manifest, config_digest)
    return resolved, {"model": model, "effort": effort, "effort_source": effort_source, "tool_manifest_digest": tool_manifest, "config_digest": config_digest, "system_identity": system_identity}


def native_cell_failure(cell: Cell, observation: tuple[Cell, dict[str, str]] | None) -> tuple[str, str, str] | None:
    if cell.cell_kind == "native_default" and cell.baseline_id is None and observation is None:
        return ("harness", "collect", "native_cell_identity_unresolved")
    return None


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
    explicit_code = exception.get("reliability_code") if isinstance(exception, dict) else None
    if isinstance(explicit_code, str) and re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", explicit_code):
        if explicit_code == "adapter_attestation_missing":
            return "harness", "collect", explicit_code
        if "timeout" in explicit_code:
            return "timeout", "run", explicit_code
        if explicit_code.startswith("provider_"):
            return "provider", "run", explicit_code
        return "harness", "run", explicit_code
    provider_reasons = {"provider_error": "provider_request_failed", "provider_rate_limited": "provider_rate_limited", "provider_authentication_failed": "provider_authentication_failed", "provider_budget_exceeded": "provider_budget_exceeded"}
    provider_exceptions = {"AuthenticationError": "provider_authentication_failed", "RateLimitError": "provider_rate_limited", "BudgetExceededError": "provider_budget_exceeded", "ProviderError": "provider_request_failed"}
    if reason in {"adapter_attestation_missing", "adapter_attestation_invalid"}:
        return "harness", "collect", reason
    if reason in provider_reasons:
        return "provider", "run", provider_reasons[reason]
    if exception_type in provider_exceptions:
        return "provider", "run", provider_exceptions[exception_type]
    if reason in {"verifier_reward_missing", "verifier_reward_invalid", "grader_report_missing", "grader_report_invalid", "grader_missing"}:
        return "harness", "grade", reason
    if reason == "turn_limit_exceeded":
        return "timeout", "run", "adapter_turn_limit_exceeded"
    if reason == "timeout" or exception_type in {"TimeoutError", "DeadlineExceededError"}:
        return "timeout", "run", "adapter_timeout"
    if reason == "setup_error" or exception_type in {"SetupError", "BootstrapError", "InstallError"}:
        return "harness", "launch", "adapter_setup_failed"
    if reason in {"transport_error", "connection_error"} or exception_type in {"TransportError", "ConnectionError"}:
        return "transport", "run", "transport_request_failed"
    if exception_type or attestation.get("status") == "failed" or reason:
        return "harness", "run", "adapter_execution_failed"
    if transcript_path is None or not transcript_path.is_file():
        return "transcript", "collect", "transcript_missing"
    return None


def reliability_detail(trial: HarborTrial, attestation: Attestation, failure: tuple[str, str, str]) -> dict[str, object]:
    exception = trial.get("exception_info")
    return {
        "schema_version": "harness_census.reliability_evidence.v1",
        "failure_class": failure[0],
        "failure_stage": failure[1],
        "failure_code": failure[2],
        "exception_type": exception.get("exception_type") if isinstance(exception, dict) else None,
        "exception_message": _sanitize_failure_text(str(exception.get("exception_message", ""))) if isinstance(exception, dict) else None,
        "attestation_status": attestation.get("status"),
        "attestation_reason": _sanitize_failure_text(str(attestation.get("reason", ""))) or None,
    }

def trial_timestamp(trial: HarborTrial, field: str) -> str:
    value = trial.get(field)
    if isinstance(value, str) and value.strip():
        return value
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json_or_failure(path: Path) -> tuple[object | None, str | None]:
    if not path.is_file():
        return None, "missing"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, "invalid"


def _matches_json_digest(path: Path, expected: str) -> bool:
    value, error = _read_json_or_failure(path)
    return error is None and digest(value) == expected


def adapter_identity_payload(cell: Cell, record: TaskRecord, attestation: Attestation, stage_digest: str, context_ref: str, context_manifest_ref: str, context_pack_ref: str, tool_manifest_ref: str | None, authority_hosts: list[str], failure: tuple[str, str, str] | None, harbor_result_path: Path, root: Path) -> dict[str, object]:
    config_digest = attestation.get("config_digest")
    tool_digest = attestation.get("tool_manifest_digest")
    payload: dict[str, object] = {
        "trial_id": f"{cell.cell_id}--{record.task_id}",
        "crucible_run_id": f"{CAMPAIGN_ID}--{cell.cell_id}--{record.task_id}",
        "cell_id": cell.cell_id,
        "cell_run_id": cell.cell_run_id,
        "campaign_id": CAMPAIGN_ID,
        "stage_manifest_digest": sha256_ref(stage_digest),
        "source_cluster": record.source_cluster,
        "task_id": record.task_id,
        "task_digest": sha256_ref(record.task_digest),
        "comparison_task_digest": sha256_ref(record.comparison_task_digest),
        "cell_kind": cell.cell_kind,
        "composition": cell.composition,
        "composition_digest": sha256_ref(cell.composition_digest),
        "adapter_digest": sha256_ref(cell.adapter_digest),
        "mcp_digest": sha256_ref(mcp_identity_digest()),
        "agent_kwargs": dict(cell.agent_kwargs),
        "agent_kwargs_digest": sha256_ref(agent_kwargs_identity_digest(cell.agent_kwargs)),
        "agent_allowed_hosts": authority_hosts,
        "agent_allowed_hosts_digest": sha256_ref(agent_allowed_hosts_identity_digest(cell)),
        "task_set_digest": sha256_ref(cell.task_set_digest),
        "task_set_size": cell.task_set_size,
        "retry_policy_digest": sha256_ref(cell.retry_policy_digest),
        "agent_kwargs_base_digest": sha256_ref(cell.agent_kwargs_base_digest),
        "context_digest": context_ref,
        "context_manifest_digest": context_manifest_ref,
        "context_pack_digest": context_pack_ref,
        "skill_digest": sha256_ref(record.skill_digest),
        "tool_manifest_digest": tool_manifest_ref,
        "network_mode": cell.network_mode,
        "transport_network_mode": cell.transport_network_mode,
        "network_enforcement": cell.network_enforcement,
        "task_network_enforcement": cell.task_network_enforcement,
        "gateway_digests": list(cell.gateway_digests),
        "gateway_dockerfile_digests": list(cell.gateway_dockerfile_digests),
        "compose_digests": list(cell.compose_digests),
        "dockerfile_digest": sha256_ref(record.dockerfile_digest),
        "gateway_digest": sha256_ref(record.gateway_digest),
        "gateway_dockerfile_digest": sha256_ref(record.gateway_dockerfile_digest),
        "compose_digest": sha256_ref(record.compose_digest),
        "row_id": sha256_ref(cell.row_id) if cell.row_id else None,
        "cohort_id": sha256_ref(cell.cohort_id) if cell.cohort_id else None,
        "baseline_id": sha256_ref(cell.baseline_id) if cell.baseline_id else None,
        "profile_digest": sha256_ref(cell.profile_digest),
        "provider_route_resolved": cell.provider_route_resolved,
        "provider_effort_resolved": cell.provider_effort_resolved,
        "default_resolution_source": cell.default_resolution_source,
        "effort_source": cell.effort_source,
        "response_effort_attestation": attestation.get("effort"),
    }
    if isinstance(config_digest, str) and isinstance(tool_digest, str) and config_digest and tool_digest:
        payload["config_digest"] = sha256_ref(config_digest)
        payload["system_identity"] = cell.observed_system_identity(config_digest, tool_digest)
    if failure is not None:
        payload.update({"failure_class": failure[0], "failure_stage": failure[1], "failure_code": failure[2], "failure_detail_ref": f"sha256:{bytes_digest(harbor_result_path.read_bytes())}@{harbor_result_path.relative_to(root).as_posix()}"})
    return {key: value for key, value in payload.items() if value is not None}

def exchange_envelopes(root: Path, cell: Cell, record: TaskRecord, trial_dir: Path, attestation_entry: AttestationEntry, stage_digest: str, cell_failure: tuple[str, str, str] | None) -> ExchangePaths:
    task_id = record.task_id
    generated_grader_path = cell.cell_dir / record.task_dir / "tests" / "verify.py"
    harbor_result_path = trial_dir / "result.json"
    trial_value, trial_error = _read_json_or_failure(harbor_result_path)
    trial_raw = cast(HarborTrial, trial_value if isinstance(trial_value, dict) else {"exception_info": {"exception_type": "HarborTrialMalformed", "exception_message": "Harbor trial result is missing or malformed"}})
    dynamic_hosts = (((trial_raw.get("config") or {}).get("agent") or {}).get("extra_allowed_hosts") if isinstance(trial_raw.get("config"), dict) else None)
    attestation, transcript = attestation_entry["record"], attestation_entry["transcript_path"]
    failure = classify_reliability(trial_raw, attestation, transcript)
    if failure is None:
        failure = cell_failure
    if trial_error and failure is None:
        failure = ("harness", "collect", "harbor_trial_malformed")
    if dynamic_hosts not in (None, []) and failure is None:
        failure = ("harness", "launch", "harbor_dynamic_network_override")
    reward_path, report_path = trial_dir / "verifier" / "reward.json", trial_dir / "verifier" / "grader-report.json"
    reward_raw, reward_error = _read_json_or_failure(reward_path)
    report_raw, report_error = _read_json_or_failure(report_path)
    reward_value = harbor_reward_value(reward_raw)
    if failure is None and not generated_grader_path.is_file():
        failure = ("harness", "grade", "grader_missing")
    if failure is None and reward_error == "missing":
        failure = ("harness", "grade", "verifier_reward_missing")
    elif failure is None and reward_error == "invalid":
        failure = ("harness", "grade", "verifier_reward_invalid")
    elif failure is None and reward_value is None:
        failure = ("harness", "grade", "verifier_reward_invalid")
    if failure is None and report_error == "missing":
        failure = ("harness", "grade", "grader_report_missing")
    elif failure is None and (report_error == "invalid" or not isinstance(report_raw, dict)):
        failure = ("harness", "grade", "grader_report_invalid")
    grader_digest = record.grader_digest
    trial_id, run_id = f"{cell.cell_id}--{task_id}", f"{CAMPAIGN_ID}--{cell.cell_id}--{task_id}"
    instruction_file = cell.cell_dir / record.task_dir / "instruction.md"
    instruction_bytes = instruction_file.read_bytes()
    stage_ref = sha256_ref(stage_digest)
    context_ref = sha256_ref(bytes_digest(instruction_bytes))
    context_manifest_ref = sha256_ref(record.context_manifest_digest)
    context_pack_ref = sha256_ref(record.context_pack_digest)
    skill_ref = sha256_ref(record.skill_digest)
    raw_tool_manifest = attestation.get("tool_manifest_digest")
    tool_manifest_ref = sha256_ref(raw_tool_manifest) if isinstance(raw_tool_manifest, str) and raw_tool_manifest else None
    authority_network = "allowlist" if cell.network_enforcement == NATIVE_NETWORK_ENFORCEMENT else "deny"
    authority_hosts = list(cell_allowed_hosts(cell)) if authority_network == "allowlist" else []
    payload = adapter_identity_payload(cell, record, attestation, stage_digest, context_ref, context_manifest_ref, context_pack_ref, tool_manifest_ref, authority_hosts, failure, harbor_result_path, root)
    cell_prefix = f"cells/{cell.cell_id}"
    workspace_path = f"{cell_prefix}/{record.task_dir}/environment/repo"
    instruction_path = f"{cell_prefix}/{record.task_dir}/instruction.md"
    model_requested, effort_requested = cell.model_requested, cell.effort_requested
    candidate = {"kind": "agent", "harness": cell.harness, "harness_version": cell.harness_version, "model": model_parts(model_requested) if model_requested is not None else None, "reasoning_effort": effort_requested, "toolset_hash": tool_manifest_ref}
    request = {"schema_version": "crucible.runner_exchange_request.v1", "exchange_id": f"{run_id}--{task_id}", "task_id": task_id, "cell_id": cell.cell_id, "cell_run_id": cell.cell_run_id, "task_set_digest": sha256_ref(cell.task_set_digest), "task_set_size": cell.task_set_size, "retry_policy_digest": sha256_ref(cell.retry_policy_digest), "agent_kwargs_base_digest": sha256_ref(cell.agent_kwargs_base_digest), "adapter": {"name": f"crucible.harbor_agents.{cell.harness}", "version": cell.harness_version, "digest": sha256_ref(cell.adapter_digest)}, "candidate": candidate, "capabilities": ["workspace_edit", "transcript", "usage"], "input": {"workspace": workspace_path, "instruction": instruction_path, "context": [], "digest": sha256_ref(bytes_digest((root / instruction_path).read_bytes()))}, "authority": {"filesystem_roots": [workspace_path, instruction_path], "network": authority_network, "allowed_hosts": authority_hosts, "credential_refs": []}, "limits": {"timeout_ms": 900000, "max_output_bytes": 1048576, "cpu_millicores": 1000, "memory_mb": 1024, "storage_mb": 2048}, "provenance": {"repo": load_tasks()[task_id].source_repository, "git_sha": load_tasks()[task_id].source_sha, "invocation_id": f"{run_id}--{task_id}"}, "trust": {"required_evidence_kinds": ["final_state", "transcript"], "require_transcript": True, "require_usage": True, "require_cost": False, "require_response_model": model_requested is not None}, "adapter_payload": payload}
    request.update({"gateway_digests": list(cell.gateway_digests), "gateway_dockerfile_digests": list(cell.gateway_dockerfile_digests), "compose_digests": list(cell.compose_digests)})
    request.update({"dockerfile_digest": sha256_ref(record.dockerfile_digest), "gateway_digest": sha256_ref(record.gateway_digest), "gateway_dockerfile_digest": sha256_ref(record.gateway_dockerfile_digest), "compose_digest": sha256_ref(record.compose_digest)})
    attestation_path = attestation_entry["attestation_path"]
    evidence: list[dict[str, object]] = [{"kind": "harbor_trial", "path": harbor_result_path.relative_to(root).as_posix(), "sha256": bytes_digest(harbor_result_path.read_bytes()), "media_type": "application/json"}]
    if failure is None:
        final = trial_dir / "verifier" / "test-stdout.txt"
        if not final.is_file():
            final = reward_path
        if not final.is_file():
            failure = ("harness", "grade", "grader_evidence_missing")
        else:
            evidence.append({"kind": "final_state", "path": final.relative_to(root).as_posix(), "sha256": bytes_digest(final.read_bytes()), "media_type": "text/plain"})
    for path, kind in ((reward_path, "verifier_reward"), (report_path, "grader_report")):
        if path.is_file():
            evidence.append({"kind": kind, "path": path.relative_to(root).as_posix(), "sha256": bytes_digest(path.read_bytes()), "media_type": "application/json"})
    if transcript is not None and transcript.is_file():
        evidence.append({"kind": "transcript", "path": transcript.relative_to(root).as_posix(), "sha256": bytes_digest(transcript.read_bytes()), "media_type": "application/x-ndjson"})
    evidence.append({"kind": "attestation", "path": attestation_path.relative_to(root).as_posix(), "sha256": bytes_digest(attestation_path.read_bytes()), "media_type": "application/json"})
    if failure is not None:
        harbor_logs = [trial_dir.parent / "harbor-run.log"]
        if len(trial_dir.parents) > 1:
            harbor_logs.append(trial_dir.parents[1] / "harbor-run.log")
        for harbor_log in dict.fromkeys(harbor_logs):
            if harbor_log.is_file():
                evidence.append({"kind": "harbor_run_log", "path": harbor_log.relative_to(root).as_posix(), "sha256": bytes_digest(harbor_log.read_bytes()), "media_type": "text/plain"})
    source_attestation = attestation.get("source_attestation_path")
    if isinstance(source_attestation, str) and source_attestation:
        original_path = trial_dir / source_attestation
        if original_path.is_file():
            evidence.append({"kind": "attestation_original", "path": original_path.relative_to(root).as_posix(), "sha256": bytes_digest(original_path.read_bytes()), "media_type": "application/json"})
    observed = attestation.get("observed_identities") or []
    elapsed = attestation.get("elapsed_seconds")
    usage = {"input_tokens": None, "output_tokens": None, "cache_tokens": None, "cost_usd": None, "latency_ms": max(1, int(float(elapsed) * 1000))} if isinstance(elapsed, (int, float)) and math.isfinite(float(elapsed)) else None
    result: dict[str, object] = {"schema_version": "crucible.runner_exchange_result.v1", "exchange_id": request["exchange_id"], "cell_id": cell.cell_id, "cell_run_id": cell.cell_run_id, "task_set_digest": sha256_ref(cell.task_set_digest), "task_set_size": cell.task_set_size, "retry_policy_digest": sha256_ref(cell.retry_policy_digest), "agent_kwargs_base_digest": sha256_ref(cell.agent_kwargs_base_digest), "adapter": request["adapter"], "candidate": candidate, "status": "timeout" if failure and failure[0] == "timeout" else "execution_error" if failure else "success", "evidence": evidence, "usage": usage, "provenance": {"response_model": observed[0] if observed else None, "started_at": trial_timestamp(trial_raw, "started_at"), "finished_at": trial_timestamp(trial_raw, "finished_at")}, "adapter_payload": payload}
    result["comparison_task_digest"] = sha256_ref(record.comparison_task_digest)
    result.update({"context_digest": context_ref, "context_manifest_digest": context_manifest_ref, "context_pack_digest": context_pack_ref, "skill_digest": skill_ref, "skill_count": record.skill_count})
    result.update({"gateway_digests": list(cell.gateway_digests), "gateway_dockerfile_digests": list(cell.gateway_dockerfile_digests), "compose_digests": list(cell.compose_digests)})
    result.update({"dockerfile_digest": sha256_ref(record.dockerfile_digest), "gateway_digest": sha256_ref(record.gateway_digest), "gateway_dockerfile_digest": sha256_ref(record.gateway_dockerfile_digest), "compose_digest": sha256_ref(record.compose_digest)})
    if failure is None:
        result["output"] = {"summary": "Harbor task completed", "primary_artifact": evidence[1]["path"], "metadata": {"reward": reward_value, "network_mode": cell.network_mode, "transport_network_mode": cell.transport_network_mode, "network_enforcement": cell.network_enforcement, "task_network_enforcement": cell.task_network_enforcement}}
    else:
        retryable = failure[0] in {"provider", "timeout", "transport"}
        result["error"] = {"code": failure[2], "message": _sanitize_failure_text(_failure_text(trial_raw, attestation)) or "Harbor reliability failure", "retryable": retryable, "detail": reliability_detail(trial_raw, attestation, failure)}
    exchange_dir = confined_path(root, "exchange", cell.cell_id, task_id)
    instruction_path = confined_path(root, "cells", cell.cell_id, *record.task_dir.split("/"), "instruction.md")
    manifest_path = confined_path(root, "context", "manifests", f"{record.context_manifest_digest}.json")
    pack_path = confined_path(root, "context", "packs", f"{record.context_pack_digest}.md")
    if not instruction_path.is_file() or bytes_digest(instruction_path.read_bytes()) != record.context_digest:
        fail(f"staged instruction identity changed for {record.task_id}")
    if not _matches_json_digest(manifest_path, record.context_manifest_digest):
        fail(f"staged context manifest identity changed for {record.task_id}")
    if not pack_path.is_file() or bytes_digest(pack_path.read_bytes()) != record.context_pack_digest:
        fail(f"staged context pack identity changed for {record.task_id}")
    exchange_dir.mkdir(parents=True, exist_ok=True)
    request_path, result_path, trial_path, grader_path = exchange_dir / "request.json", exchange_dir / "result.json", exchange_dir / "trial.json", exchange_dir / "grader.json"
    write_json(request_path, request)
    write_json(result_path, result)
    trial_record: dict[str, object] = {"schema_version": "harness_census.trial_receipt.v1", "campaign_id": CAMPAIGN_ID, "trial_id": trial_id, "crucible_run_id": run_id, "cell_id": cell.cell_id, "cell_run_id": cell.cell_run_id, "task_set_digest": sha256_ref(cell.task_set_digest), "task_set_size": cell.task_set_size, "retry_policy_digest": sha256_ref(cell.retry_policy_digest), "agent_kwargs_base_digest": sha256_ref(cell.agent_kwargs_base_digest), "source_cluster": record.source_cluster, "task_name": task_id, "stage_manifest_digest": stage_ref, "network_mode": cell.network_mode, "transport_network_mode": cell.transport_network_mode, "network_enforcement": cell.network_enforcement, "task_network_enforcement": cell.task_network_enforcement, "assistant_turns": trial_raw.get("assistant_turns"), "verifier_result": trial_raw.get("verifier_result")}
    trial_record.update({"context_digest": context_ref, "context_manifest_digest": context_manifest_ref, "context_pack_digest": context_pack_ref, "skill_digest": skill_ref, "skill_count": record.skill_count})
    trial_record["comparison_task_digest"] = sha256_ref(record.comparison_task_digest)
    trial_record.update({"gateway_digests": list(cell.gateway_digests), "gateway_dockerfile_digests": list(cell.gateway_dockerfile_digests), "compose_digests": list(cell.compose_digests)})
    trial_record.update({"dockerfile_digest": sha256_ref(record.dockerfile_digest), "gateway_digest": sha256_ref(record.gateway_digest), "gateway_dockerfile_digest": sha256_ref(record.gateway_dockerfile_digest), "compose_digest": sha256_ref(record.compose_digest)})
    trial_record.update({"task_id": task_id, "row_id": sha256_ref(cell.row_id) if cell.row_id else None, "cohort_id": sha256_ref(cell.cohort_id) if cell.cohort_id else None, "baseline_id": sha256_ref(cell.baseline_id) if cell.baseline_id else None, "profile_digest": sha256_ref(cell.profile_digest), "model_requested": cell.model_requested, "effort_requested": cell.effort_requested, "provider_route_resolved": cell.provider_route_resolved, "provider_effort_resolved": cell.provider_effort_resolved})
    if failure is not None:
        trial_record.update({"trial_status": "reliability_failure", "failure_class": failure[0], "failure_stage": failure[1], "failure_code": failure[2], "failure_detail": reliability_detail(trial_raw, attestation, failure)})
    trial_record = {key: value for key, value in trial_record.items() if value is not None}
    write_json(trial_path, trial_record)
    if failure is None:
        grader_record: dict[str, object] = {"schema_version": "harness_census.grader_receipt.v1", "campaign_id": CAMPAIGN_ID, "trial_id": trial_id, "task_id": task_id, "row_id": sha256_ref(cell.row_id) if cell.row_id else None, "cohort_id": sha256_ref(cell.cohort_id) if cell.cohort_id else None, "baseline_id": sha256_ref(cell.baseline_id) if cell.baseline_id else None, "grader_identity": "harness_census_deterministic", "grader_digest": grader_digest, "hard_pass": reward_value == 1.0, "task_points": reward_value, "grader_ms": None}
        write_json(grader_path, {key: value for key, value in grader_record.items() if value is not None})
    else:
        grader_path = None
    return ExchangePaths(request_path, result_path, trial_path, grader_path)


def ingest_task(crucible: Path, root: Path, cell: Cell, record: TaskRecord, paths: ExchangePaths, stage_digest: str, tool_manifest_digest: str | None) -> dict[str, object]:
    db = confined_path(root, "runs", "campaign.sqlite")
    instruction_path = confined_path(root, "cells", cell.cell_id, *record.task_dir.split("/"), "instruction.md")
    manifest_path = confined_path(root, "context", "manifests", f"{record.context_manifest_digest}.json")
    pack_path = confined_path(root, "context", "packs", f"{record.context_pack_digest}.md")
    if not instruction_path.is_file() or bytes_digest(instruction_path.read_bytes()) != record.context_digest:
        fail(f"staged instruction identity changed for {record.task_id}")
    if not _matches_json_digest(manifest_path, record.context_manifest_digest):
        fail(f"staged context manifest identity changed for {record.task_id}")
    if not pack_path.is_file() or bytes_digest(pack_path.read_bytes()) != record.context_pack_digest:
        fail(f"staged context pack identity changed for {record.task_id}")
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
        "--source-cluster", record.source_cluster,
        "--task-digest", sha256_ref(record.task_digest),
        "--comparison-task-digest", sha256_ref(record.comparison_task_digest),
        "--cell-kind", cell.cell_kind,
        "--profile-digest", sha256_ref(cell.profile_digest),
        "--composition", cell.composition,
        "--context-digest", sha256_ref(record.context_digest),
        "--skill-digest", sha256_ref(record.skill_digest),
        "--mcp-digest", sha256_ref(mcp_identity_digest()),
    ]
    if tool_manifest_digest is not None:
        command += ["--tool-manifest-digest", sha256_ref(tool_manifest_digest)]
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
    result_run = subprocess.run(command, cwd=root, env=safe_runtime_environment(), text=True, capture_output=True, check=False)
    if result_run.returncode:
        fail(f"Runner Exchange ingest failed for {record.task_id}: {_sanitize_failure_text(result_run.stderr[-1000:])}")
    try:
        return cast(dict[str, object], json.loads(result_run.stdout))
    except json.JSONDecodeError as error:
        fail(f"Runner Exchange ingest returned invalid JSON for {record.task_id}: {error}")


def compact_receipt(value: Receipt) -> dict[str, object]:
    compact = {key: value[key] for key in COMPACT_RECEIPT_KEYS if key in value and isinstance(value[key], (str, int, float, bool))}
    compact["receipt_digest"] = digest(compact)
    return compact




def run_cell(root: Path, cell: Cell, crucible: Path, harbor: Path, stage_digest: str, expected_cell_digest: str | None = None, task_ids: list[str] | None = None) -> None:
    if expected_cell_digest is not None and cell_stage_digest(cell.cell_dir, include_workspace=False) != expected_cell_digest:
        fail(f"staged cell bytes changed before run: {cell.cell_id}")
    declared = {record.task_id for record in cell.task_records}
    if task_ids is not None:
        if not set(task_ids) or set(task_ids) - declared or len(set(task_ids)) != len(task_ids):
            fail(f"task selection is invalid for cell: {cell.cell_id}")
    selected = [record for record in cell.task_records if task_ids is None or record.task_id in task_ids]
    if not selected:
        fail(f"no tasks are selected for cell: {cell.cell_id}")
    output = cell.cell_dir / "results"
    output.mkdir(exist_ok=True)
    command = [str(crucible), "run", str(cell.spec_path), "--out", str(output), "--json"]
    if task_ids is not None and set(task_ids) != declared:
        for task_id in task_ids:
            command += ["--task", task_id]
    environment = safe_runtime_environment(harbor)
    result_run = subprocess.run(command, cwd=cell.cell_dir, env=environment, text=True, capture_output=True, check=False)
    # A non-zero Crucible run still leaves per-task failure evidence when the Harbor executor can continue.
    # Missing task artifacts are materialized by collect_attestations as denominator-excluded attempts.
    selected_attestations = collect_attestations(output, cell, selected)
    if len(selected_attestations) != len(selected):
        fail(f"staged cell run left tasks without evidence: {cell.cell_id}")
    all_attestations = selected_attestations
    if cell.cell_kind == "native_default" and len(selected) != len(cell.task_records):
        all_attestations = collect_attestations(output, cell, materialize_missing=False)
    observation = native_observation(cell, all_attestations)
    cell_failure = native_cell_failure(cell, observation) if len(all_attestations) == len(cell.task_records) else None
    observed_identity: dict[str, str] = {}
    if observation is not None:
        cell, observed_identity = observation
    passed = [entry for entry in selected_attestations if entry["record"].get("status") == "passed"]
    receipts: list[dict[str, object]] = []
    for record, attestation in zip(selected, selected_attestations):
        raw_tool_manifest = attestation["record"].get("tool_manifest_digest")
        tool_manifest_digest = raw_tool_manifest if isinstance(raw_tool_manifest, str) and raw_tool_manifest else None
        paths = exchange_envelopes(root, cell, record, attestation["trial_dir"], attestation, stage_digest, cell_failure)
        if expected_cell_digest is not None and cell_stage_digest(cell.cell_dir, include_workspace=False) != expected_cell_digest:
            fail(f"staged cell bytes changed before ingest: {cell.cell_id}")
        receipts.append(ingest_task(crucible, root, cell, record, paths, stage_digest, tool_manifest_digest))
    observed = sorted({entry["record"]["observed_identities"][0] for entry in passed if entry["record"].get("observed_identities")})
    observed_efforts = sorted({entry["record"]["effort"] for entry in passed if entry["record"].get("effort")})
    observed_tools = sorted({entry["record"]["tool_manifest_digest"] for entry in passed if entry["record"].get("tool_manifest_digest")})
    observed_configs = sorted({entry["record"]["config_digest"] for entry in passed if entry["record"].get("config_digest")})
    observed_systems = sorted({cell.observed_system_identity(entry["record"]["config_digest"], entry["record"]["tool_manifest_digest"]) for entry in passed if isinstance(entry["record"].get("config_digest"), str) and isinstance(entry["record"].get("tool_manifest_digest"), str)})
    if len(passed) == len(selected_attestations) and (observed != [cell.provider_route_resolved] or observed_efforts != [cell.provider_effort_resolved]):
        fail(f"cell observed model or effort identity is not singular: {cell.cell_id}")
    attestation_receipts = [{"task_id": entry["task_id"], "attestation_ref": entry["attestation_ref"], "attestation_digest": entry["attestation_digest"], "transcript_ref": entry["transcript_ref"], "record": entry["record"]} for entry in selected_attestations]
    compact_receipts = [compact_receipt(cast(Receipt, receipt)) for receipt in receipts]
    if cell.cell_kind == "native_default" and observation is not None:
        baseline_summary = {"schema_version": "harness_census.native_baseline_summary.v1", "campaign_id": CAMPAIGN_ID, "stage_manifest_digest": stage_digest, "cell_id": cell.cell_id, "cell_run_id": cell.cell_run_id, "baseline_id": cell.baseline_id, "harness": cell.harness, "harness_version": cell.harness_version, "profile_digest": cell.profile_digest, "task_set_digest": cell.task_set_digest, "observed_model": observed_identity["model"], "observed_effort": observed_identity["effort"], "effort_source": observed_identity["effort_source"], "tool_manifest_digest": observed_identity["tool_manifest_digest"], "config_digest": observed_identity["config_digest"], "system_identity": observed_identity["system_identity"], "receipt_digests": [receipt["receipt_digest"] for receipt in compact_receipts], "status": "valid" if len(compact_receipts) == len(cell.task_records) and all(receipt.get("trial_status") == "success" for receipt in compact_receipts) else "invalid"}
        write_json(confined_path(root, "baselines", str(cell.baseline_id), "summary.json"), baseline_summary)
    if len(selected) == len(cell.task_records):
        write_json(cell.cell_dir / "result.json", {"schema_version": "harness_census.normalized_result.v1", "campaign_id": CAMPAIGN_ID, "cell_id": cell.cell_id, "cell_run_id": cell.cell_run_id, "task_set_digest": cell.task_set_digest, "task_set_size": cell.task_set_size, "retry_policy_digest": cell.retry_policy_digest, "agent_kwargs_base_digest": cell.agent_kwargs_base_digest, "stage_manifest_digest": stage_digest, "return_code": result_run.returncode, "model_requested": cell.model_requested, "effort_requested": cell.effort_requested, "provider_route_resolved": cell.provider_route_resolved, "provider_effort_resolved": cell.provider_effort_resolved, "response_model": observed[0] if len(observed) == 1 else None, "observed_models": observed, "response_effort": observed_efforts[0] if len(observed_efforts) == 1 else None, "observed_efforts": observed_efforts, "observed_tool_manifest_digests": observed_tools, "observed_config_digests": observed_configs, "observed_system_identities": observed_systems, "effort_source": cell.effort_source, "network_mode": cell.network_mode, "transport_network_mode": cell.transport_network_mode, "network_enforcement": cell.network_enforcement, "task_network_enforcement": cell.task_network_enforcement, "row_id": cell.row_id, "cohort_id": cell.cohort_id, "baseline_id": cell.baseline_id, "profile_digest": cell.profile_digest, "agent_kwargs": dict(cell.agent_kwargs), "agent_allowed_hosts": list(cell.agent_allowed_hosts), "attestations": attestation_receipts, "attestation_digests": [entry["attestation_digest"] for entry in selected_attestations], "runner_exchange_receipts": compact_receipts})
