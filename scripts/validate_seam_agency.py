#!/usr/bin/env python3
"""Qualify Bench-owned Seam Agency gold without acting as an agent runner."""

from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "benchmarks" / "seam-agency-v0"
MODES = {"build", "extend", "repair", "critique"}
AI_NECESSITY = {"required", "unnecessary", "mixed"}


def fail(message: str) -> None:
    raise SystemExit(f"seam-agency check: {message}")


def load_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot load {path.relative_to(ROOT)}: {exc}")


def validate_manifest() -> list[dict]:
    manifest = load_json(PACKAGE / "qualification.json")
    if manifest.get("schema_version") != "bench.seam_agency_qualification.v0":
        fail("unexpected qualification schema")
    if manifest.get("owner") != "bench":
        fail("Bench must be the benchmark owner")
    capability = manifest.get("runtime_capability", {})
    expected_capability = {
        "manifest_schema": "bench.runtime_capabilities.v1",
        "capability_id": "semantic.generate.v1",
        "transport": "json_stdio_once",
        "command": "crucible-semantic",
        "request_schema": "bench.semantic_generate.request.v1",
        "result_schema": "bench.semantic_generate.result.v1",
        "content_trust": "untrusted",
        "identical_across_all_tasks": True,
    }
    if any(capability.get(key) != value for key, value in expected_capability.items()):
        fail("qualification manifest has an invalid shared runtime capability")
    expected_policies = {
        "build-publication-assistant": "positive_causal_full_input",
        "build-incident-grouping": "positive_causal_full_input",
        "build-claim-lease": "zero_calls_plus_capability_absent",
        "extend-provider-routing": "positive_causal_after_deterministic_eligibility",
        "extend-comparison-attribution": "zero_calls_plus_capability_absent",
        "repair-memory-extraction": "positive_causal_full_input",
        "critique-operator-action-router": "observed_non_scoring",
    }
    if capability.get("per_task_receipt_policy") != expected_policies:
        fail("qualification manifest has invalid per-task capability policies")
    if capability.get("exact_positive_call_count_scored") is not False:
        fail("qualification manifest must not score exact positive capability call count")
    reporting = manifest.get("reporting", {})
    if reporting.get("forbid_pooled_mode_score") is not True:
        fail("manifest must forbid a pooled mode score")
    if set(reporting.get("separate_rates", [])) != MODES:
        fail("manifest must require separate Build, Extend, Repair, and Critique rates")
    tasks = manifest.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 7:
        fail("qualification manifest must contain exactly seven tasks")
    ids = [task.get("id") for task in tasks]
    if len(ids) != len(set(ids)):
        fail("qualification task ids must be unique")
    if {task.get("mode") for task in tasks} != MODES:
        fail("qualification set must cover Build, Extend, Repair, and Critique")
    for task in tasks:
        missing = [
            key
            for key in (
                "id",
                "mode",
                "ai_necessity",
                "seam_family",
                "visible_request",
                "invariants",
                "forbidden_outcomes",
                "required_mutations",
                "hidden_policy",
                "materialized",
            )
            if key not in task
        ]
        if missing:
            fail(f"{task.get('id', '<unknown>')} missing fields: {', '.join(missing)}")
        if task["mode"] not in MODES or task["ai_necessity"] not in AI_NECESSITY:
            fail(f"{task['id']} has an invalid mode or AI-necessity ruling")
        for key in ("invariants", "forbidden_outcomes", "required_mutations"):
            if len(task[key]) < 2:
                fail(f"{task['id']} must name at least two {key.replace('_', ' ')}")
        if task["materialized"]:
            task_dir = PACKAGE / task.get("task_dir", "")
            if not task_dir.is_dir():
                fail(f"{task['id']} materialized task directory is missing")
            if task.get("reference_dirs") != ["solution", "solution-alt"]:
                fail(f"{task['id']} must declare both structurally distinct references")
            if any(not (task_dir / name).is_dir() for name in task["reference_dirs"]):
                fail(f"{task['id']} has a missing reference directory")
            references = load_json(task_dir / "references.json").get("references", [])
            if [reference.get("path") for reference in references] != task["reference_dirs"]:
                fail(f"{task['id']} reference structure manifest drifted")
            structures = [reference.get("structure") for reference in references]
            if any(not structure for structure in structures) or len(set(structures)) != 2:
                fail(f"{task['id']} must declare two distinct reference structures")
            behavioral = [reference.get("behavioral_difference") for reference in references]
            if any(not difference for difference in behavioral) or len(set(behavioral)) != 2:
                fail(f"{task['id']} must declare two behaviorally distinct acceptable references")
            proof_markers = [reference.get("proof_marker") for reference in references]
            if any(not marker for marker in proof_markers) or len(set(proof_markers)) != 2:
                fail(f"{task['id']} must declare two distinct executable behavior proof markers")
    materialized = [task for task in tasks if task["materialized"]]
    if len(materialized) != 7 or Counter(task["mode"] for task in materialized) != {
        "build": 3,
        "extend": 2,
        "repair": 1,
        "critique": 1,
    }:
        fail("materialized corpus must be 3 Build, 2 Extend, 1 Repair, and 1 Critique")
    return materialized


def validate_shared_capability(materialized: list[dict]) -> None:
    task_dirs = [PACKAGE / task["task_dir"] for task in materialized]
    for relative in (
        Path("environment/capabilities.json"),
        Path("environment/crucible-semantic"),
        Path("tests/crucible-semantic"),
        Path("tests/semantic_fixture.py"),
    ):
        contents = [(task_dir / relative).read_bytes() for task_dir in task_dirs]
        if len(set(contents)) != 1:
            fail(f"shared capability file differs across the seven-task corpus: {relative}")
    capability = load_json(task_dirs[0] / "environment" / "capabilities.json")
    if capability.get("schema_version") != "bench.runtime_capabilities.v1":
        fail("candidate-visible capability manifest has an invalid schema")
    entries = capability.get("capabilities", [])
    if len(entries) != 1:
        fail("candidate-visible manifest must expose exactly the shared semantic capability")
    semantic = entries[0]
    if (
        semantic.get("id") != "semantic.generate.v1"
        or semantic.get("transport") != "json_stdio_once"
        or semantic.get("command") != "crucible-semantic"
        or semantic.get("content_trust") != "untrusted"
        or set(semantic.get("statuses", []))
        != {"ok", "refused", "timeout", "malformed_output", "execution_error"}
    ):
        fail("candidate-visible semantic capability contract drifted")
    for task_dir in task_dirs:
        task_config = tomllib.loads((task_dir / "task.toml").read_text())
        if task_config.get("environment", {}).get("network_mode") != "no-network":
            fail(f"{task_dir.name} must explicitly deny network access")
        for relative in ("environment/crucible-semantic", "tests/crucible-semantic"):
            if (task_dir / relative).stat().st_mode & 0o111 == 0:
                fail(f"shared capability command is not executable: {task_dir / relative}")
        instruction = (task_dir / "instruction.md").read_text()
        if "BENCH_CAPABILITIES_MANIFEST" not in instruction:
            fail(f"{task_dir.name} does not disclose the neutral capability manifest")
    publication = next(task for task in materialized if task["id"] == "build-publication-assistant")
    publication_dir = PACKAGE / publication["task_dir"]
    prompted_surface = (
        (publication_dir / "instruction.md").read_text()
        + (publication_dir / "environment" / "repo" / "packetizer.py").read_text()
    )
    if "ReviewBoundary" in prompted_surface or "reviewer" in prompted_surface.lower():
        fail("publication task still prompts the candidate with the former review boundary")
    for task_dir in task_dirs:
        verifier = (task_dir / "tests" / "verify.py").read_text()
        if "inspect.getsource" in verifier or "ast.parse" in verifier:
            fail(f"{task_dir.name} verifier must not grade candidate source shape")
    print("semantic-capability: seven identical manifests/commands and per-task receipt policies PASS")


def validate_crucible_spec(materialized: list[dict]) -> None:
    spec_path = PACKAGE / "seam-agency-v0-harbor.json"
    spec = load_json(spec_path)
    if spec.get("schema_version") != "crucible.eval_spec.v1":
        fail("generic Crucible spec has an unexpected schema")
    runner = spec.get("runner", {})
    corpus = runner.get("corpus", {})
    if runner.get("kind") != "harbor_task" or corpus.get("source") != "harbor_tasks":
        fail("generic spec must use the public harbor_task contract")
    declared = {task.get("task_id") for task in corpus.get("tasks", [])}
    expected = {task["id"] for task in materialized}
    if declared != expected:
        fail("generic Crucible spec must name exactly the seven materialized tasks")
    if shutil.which("crucible"):
        result = subprocess.run(
            ["crucible", "validate", str(spec_path), "--json"],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        report = json.loads(result.stdout)
        if report.get("valid") is not True or report.get("runnable") is not True:
            fail(f"Crucible rejected the generic spec: {report}")
        print("crucible-spec: valid=true runnable=true")
    else:
        print("crucible-spec: structural validation only (crucible not installed)")


def validate_review_surface(materialized: list[dict]) -> None:
    review_path = ROOT / "docs" / "data" / "reviews" / "seam-agency-v0-qualification.json"
    review = load_json(review_path)
    if review.get("schema_version") != "bench.qualification_review.v1":
        fail("qualification review has an unexpected schema")
    status = review.get("status", {})
    if status.get("kind") != "harbor_oracle_reference_qualification":
        fail("review must identify the evidence as Harbor oracle/reference qualification")
    if "No model candidate was run" not in status.get("headline", ""):
        fail("review must prominently state that no model candidate ran")

    spec = load_json(PACKAGE / "seam-agency-v0-harbor.json")
    corpus_config = spec["runner"]["corpus"]["config"]
    run = review.get("run", {})
    if run.get("benchmark_id") != spec.get("id"):
        fail("review benchmark identity does not match the Crucible spec")
    if run.get("runner_kind") != spec["runner"]["kind"]:
        fail("review runner identity does not match the Crucible spec")
    if run.get("harness") != corpus_config.get("agent"):
        fail("review harness does not match the declared oracle agent")
    if run.get("resource_envelope") != corpus_config.get("resource_envelope"):
        fail("review resource envelope does not match the Crucible spec")
    if run.get("model") is not None or run.get("provider") is not None:
        fail("oracle review must not invent a model or provider")
    usage = run.get("model_usage", {})
    for field in ("cost_usd", "n_input_tokens", "n_output_tokens", "n_cache_tokens"):
        if field not in usage or usage[field] is not None:
            fail(f"oracle review must preserve the raw null {field} field")
    if "Zero model cost" not in usage.get("interpretation", ""):
        fail("review must explain why oracle qualification has zero model cost")

    score = run.get("score", {})
    expected_score = {
        "metric": "harbor_reward_pass_rate",
        "successes": 7,
        "n": 7,
        "point": 1.0,
        "lower": 0.6456611570247934,
        "upper": 1.0,
        "confidence": 0.95,
        "method": "Wilson",
    }
    if score != expected_score:
        fail("review score does not match the sanitized Crucible oracle receipt")
    expected_mode_scores = [
        {
            "mode": "build",
            "successes": 3,
            "n": 3,
            "point": 1.0,
            "lower": 0.43849391955098227,
            "upper": 1.0,
            "confidence": 0.95,
            "method": "Wilson",
        },
        {
            "mode": "extend",
            "successes": 2,
            "n": 2,
            "point": 1.0,
            "lower": 0.34237195288961925,
            "upper": 1.0,
            "confidence": 0.95,
            "method": "Wilson",
        },
        {
            "mode": "repair",
            "successes": 1,
            "n": 1,
            "point": 1.0,
            "lower": 0.20654329147389294,
            "upper": 1.0,
            "confidence": 0.95,
            "method": "Wilson",
        },
        {
            "mode": "critique",
            "successes": 1,
            "n": 1,
            "point": 1.0,
            "lower": 0.20654329147389294,
            "upper": 1.0,
            "confidence": 0.95,
            "method": "Wilson",
            "interpretation": "Deterministic replay artifact qualification only; not semantic critique quality.",
        },
    ]
    if run.get("mode_scores") != expected_mode_scores:
        fail("review must report the exact separate Build, Extend, Repair, and Critique rates")

    reviewed_tasks = review.get("tasks", [])
    expected_ids = {task["id"] for task in materialized}
    if {task.get("task_id") for task in reviewed_tasks} != expected_ids:
        fail("review must render exactly the seven materialized tasks")
    declarations = {task["id"]: task for task in materialized}
    for reviewed in reviewed_tasks:
        task_id = reviewed["task_id"]
        declared = declarations[task_id]
        for review_key, declaration_key in (
            ("mode", "mode"),
            ("ai_necessity", "ai_necessity"),
            ("seam_family", "seam_family"),
            ("visible_request", "visible_request"),
        ):
            if reviewed.get(review_key) != declared.get(declaration_key):
                fail(f"review {task_id} {review_key} drifted from qualification.json")
        task_dir = PACKAGE / declared["task_dir"]
        expected_references = [
            (task_dir / reference).relative_to(ROOT).as_posix()
            for reference in declared["reference_dirs"]
        ]
        expected_verifier = (task_dir / "tests" / "verify.py").relative_to(ROOT).as_posix()
        if reviewed.get("reference_paths") != expected_references:
            fail(f"review {task_id} reference paths drifted")
        reference_structures = reviewed.get("reference_structures", [])
        if len(reference_structures) != 2 or len(set(reference_structures)) != 2:
            fail(f"review {task_id} must describe two distinct reference structures")
        references = load_json(task_dir / "references.json")["references"]
        if reviewed.get("reference_behaviors") != [
            reference["behavioral_difference"] for reference in references
        ]:
            fail(f"review {task_id} behavioral reference evidence drifted")
        if reviewed.get("reference_proof_markers") != [
            reference["proof_marker"] for reference in references
        ]:
            fail(f"review {task_id} executable reference witnesses drifted")
        if reviewed.get("verifier_path") != expected_verifier:
            fail(f"review {task_id} verifier path drifted")
        if reviewed.get("passed") is not True or reviewed.get("reward") != 1.0:
            fail(f"review {task_id} must preserve the oracle reward receipt")
        declared_mutants = load_json(task_dir / "mutants" / "manifest.json")["mutants"]
        expected_mutants = [
            {
                "id": mutant["id"],
                "expected_failure": mutant["expected_failure"],
                "failure_marker": mutant["failure_marker"],
            }
            for mutant in declared_mutants
        ]
        if reviewed.get("mutants") != expected_mutants:
            fail(f"review {task_id} mutant evidence drifted from its manifest")
        capability_receipt = reviewed.get("capability_receipt", {})
        if capability_receipt.get("capability_id") != "semantic.generate.v1":
            fail(f"review {task_id} capability receipt drifted")
        if capability_receipt.get("candidate_receipt_authorship") != "blocked":
            fail(f"review {task_id} must preserve blocked candidate receipt authorship")

    publication_receipt = next(
        task["capability_receipt"]
        for task in reviewed_tasks
        if task["task_id"] == "build-publication-assistant"
    )
    if (
        publication_receipt.get("observed") != "positive causal use"
        or publication_receipt.get("full_semantic_inputs") is not True
        or publication_receipt.get("exact_positive_call_count_scored") is not False
    ):
        fail("publication capability receipt lost its causal/full-input boundary")
    lease_receipt = next(
        task["capability_receipt"]
        for task in reviewed_tasks
        if task["task_id"] == "build-claim-lease"
    )
    if (
        lease_receipt.get("observed_calls") != 0
        or lease_receipt.get("capability_absent_recheck") != "pass"
        or "denied by Harbor" not in lease_receipt.get("network", "")
    ):
        fail("lease capability receipt lost its zero-use/absent/network boundary")
    for task_id in ("build-incident-grouping", "extend-provider-routing", "repair-memory-extraction"):
        capability = next(
            task["capability_receipt"] for task in reviewed_tasks if task["task_id"] == task_id
        )
        if (
            "positive causal use" not in capability.get("observed", "")
            or capability.get("full_semantic_inputs") is not True
            or capability.get("exact_positive_call_count_scored") is not False
        ):
            fail(f"{task_id} capability receipt lost its positive causal boundary")
    comparison_receipt = next(
        task["capability_receipt"]
        for task in reviewed_tasks
        if task["task_id"] == "extend-comparison-attribution"
    )
    if (
        comparison_receipt.get("observed_calls") != 0
        or comparison_receipt.get("capability_absent_recheck") != "pass"
    ):
        fail("comparison capability receipt lost its zero-use/absent boundary")
    critique_receipt = next(
        task["capability_receipt"]
        for task in reviewed_tasks
        if task["task_id"] == "critique-operator-action-router"
    )
    if (
        critique_receipt.get("scoring") != "observed non-scoring"
        or critique_receipt.get("semantic_quality_claim") is not None
    ):
        fail("critique receipt must remain observed non-scoring with no semantic quality claim")

    ledger_states = {group.get("state") for group in review.get("evidence_ledger", [])}
    if ledger_states != {"measured", "package_gate_only", "planned", "missing"}:
        fail("review must separate measured, package-gate-only, planned, and missing evidence")
    findings = review.get("construct_findings", [])
    if {finding.get("id") for finding in findings} != {
        "independent-ai-recognition",
        "behaviorally-distinct-references",
        "lease-concurrency-and-failure",
        "unnecessary-ai-direct-invariant",
        "controlled-semantic-fixture",
        "critique-quality-ceiling",
        "public-development-only",
    }:
        fail("review must expose the seven-task construct findings and remaining blockers")
    finding_statuses = {finding.get("id"): finding.get("status") for finding in findings}
    for finding_id in (
        "independent-ai-recognition",
        "behaviorally-distinct-references",
        "lease-concurrency-and-failure",
        "unnecessary-ai-direct-invariant",
    ):
        if finding_statuses.get(finding_id) != "resolved_public_development":
            fail(f"review must mark {finding_id} resolved only for public development qualification")
    for finding_id in ("critique-quality-ceiling", "public-development-only"):
        if finding_statuses.get(finding_id) != "benchmark_blocker":
            fail(f"review must preserve {finding_id} as a benchmark blocker")
    for finding in findings:
        for source_path in finding.get("source_paths", []):
            if not (ROOT / source_path).is_file():
                fail(f"construct finding source does not exist: {source_path!r}")
    if len(review.get("readiness_path", [])) < 4:
        fail("review must provide a concrete multi-step benchmark-readiness path")

    serialized = json.dumps(review, sort_keys=True)
    if "/Users/" in serialized or ".cache/" in serialized or "file://" in serialized:
        fail("review data leaks a local path")
    for source in review.get("sources", []):
        path = source.get("path", "")
        if not path or not (ROOT / path).exists():
            fail(f"review source path does not exist: {path!r}")

    site_manifest = load_json(ROOT / "docs" / "data" / "manifest.json")
    review_entry = next(
        (item for item in site_manifest.get("reviews", []) if item.get("id") == review["id"]),
        None,
    )
    if not review_entry or review_entry.get("url") != "seam-agency-review.html":
        fail("site manifest must link the Seam Agency qualification review")
    if "seven-task public development corpus" not in review_entry.get("tagline", ""):
        fail("site manifest review card must describe the seven-task corpus")
    page = (ROOT / "docs" / "seam-agency-review.html").read_text()
    renderer = (ROOT / "docs" / "seam-agency-review.js").read_text()
    if (
        "qualification-review" not in page
        or "evidence_ledger" not in renderer
        or "construct_findings" not in renderer
    ):
        fail("qualification review page or renderer is incomplete")

    receipt = (PACKAGE / "receipts" / "seven-task-qualification-2026-07-13.md").read_text()
    stable_identity = [
        run.get("run_id"),
        run.get("invocation_id"),
        run.get("git_sha"),
        str(run.get("created_at_unix_ms")),
    ]
    for task in reviewed_tasks:
        stable_identity.extend(
            task.get(field)
            for field in ("trial_name", "job_id", "evidence_id", "task_checksum")
        )
    if any(not value or str(value) not in receipt for value in stable_identity):
        fail("review runtime identity is not backed by the checked-in receipt")
    print("seam-agency-review: sanitized evidence joins PASS")


def overlay(source: Path, destination: Path) -> None:
    for path in sorted(source.rglob("*")):
        if path.is_file() and path.name != "solve.sh":
            target = destination / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def run_candidate(task_dir: Path, candidate: Path, *, reference_audit: bool = False) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="bench-seam-agency-") as temp:
        repo = Path(temp) / "repo"
        shutil.copytree(task_dir / "environment" / "repo", repo)
        overlay(candidate, repo)
        environment = dict(os.environ)
        if reference_audit:
            environment["BENCH_REFERENCE_AUDIT"] = "1"
        result = subprocess.run(
            [sys.executable, str(task_dir / "tests" / "verify.py"), str(repo)],
            cwd=repo,
            text=True,
            capture_output=True,
            env=environment,
        )
        output = (result.stdout + result.stderr).strip().replace("\n", " | ")
        return result.returncode, output


def qualify_task(task: dict) -> None:
    task_dir = PACKAGE / task["task_dir"]
    mutant_manifest = load_json(task_dir / "mutants" / "manifest.json")
    mutants = mutant_manifest.get("mutants", [])
    required = set(task["required_mutations"])
    declared = {mutant.get("id") for mutant in mutants}
    if not required.issubset(declared):
        fail(f"{task['id']} does not materialize every required mutation")
    if len(mutants) < 2:
        fail(f"{task['id']} needs at least two named mutants")

    reference_declarations = {
        reference["path"]: reference
        for reference in load_json(task_dir / "references.json")["references"]
    }
    for reference_name in task["reference_dirs"]:
        reference = task_dir / reference_name
        code, output = run_candidate(task_dir, reference, reference_audit=True)
        if code != 0:
            fail(f"{task['id']} reference {reference_name} failed: {output}")
        marker = reference_declarations[reference_name]["proof_marker"]
        if marker not in output:
            fail(
                f"{task['id']} reference {reference_name} did not prove its declared behavior: "
                f"expected {marker!r}; output={output}"
            )
        print(f"{task['id']}: reference {reference_name} PASS ({marker})")

    for mutant in mutants:
        candidate = task_dir / "mutants" / mutant["path"]
        code, output = run_candidate(task_dir, candidate)
        if code == 0:
            fail(f"{task['id']} mutant {mutant['id']} unexpectedly passed")
        marker = mutant.get("failure_marker")
        if not marker or marker not in output:
            fail(
                f"{task['id']} mutant {mutant['id']} failed for the wrong reason: "
                f"expected marker {marker!r}; output={output}"
            )
        print(f"{task['id']}: mutant {mutant['id']} FAIL expected reason={marker}")


def scan_public_package() -> None:
    forbidden = (
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}\b"),
        re.compile(r"OPENROUTER_API_KEY\s*=\s*[^<\s][^\s]+"),
    )
    for path in sorted(PACKAGE.rglob("*")):
        if path.is_file():
            text = path.read_text(errors="ignore")
            hit = next((pattern.pattern for pattern in forbidden if pattern.search(text)), None)
            if hit:
                fail(f"sensitive credential-shaped match {hit!r} in {path.relative_to(ROOT)}")


def main() -> None:
    materialized = validate_manifest()
    validate_shared_capability(materialized)
    validate_crucible_spec(materialized)
    validate_review_surface(materialized)
    scan_public_package()
    for task in materialized:
        qualify_task(task)
    print("seam-agency-v0: package qualification PASS (14 references, 21 mutants)")


if __name__ == "__main__":
    main()
