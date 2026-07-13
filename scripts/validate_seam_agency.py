#!/usr/bin/env python3
"""Qualify Bench-owned Seam Agency gold without acting as an agent runner."""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


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
    materialized = [task for task in tasks if task["materialized"]]
    if {(task["mode"], task["ai_necessity"]) for task in materialized} != {
        ("build", "mixed"),
        ("build", "unnecessary"),
    }:
        fail("materialized pair must be matched Build mixed/control tasks")
    return materialized


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
        fail("generic Crucible spec must name exactly the materialized pair")
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


def overlay(source: Path, destination: Path) -> None:
    for path in sorted(source.rglob("*")):
        if path.is_file() and path.name != "solve.sh":
            target = destination / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def run_candidate(task_dir: Path, candidate: Path) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="bench-seam-agency-") as temp:
        repo = Path(temp) / "repo"
        shutil.copytree(task_dir / "environment" / "repo", repo)
        overlay(candidate, repo)
        result = subprocess.run(
            [sys.executable, str(task_dir / "tests" / "verify.py"), str(repo)],
            cwd=repo,
            text=True,
            capture_output=True,
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

    reference = task_dir / "solution"
    code, output = run_candidate(task_dir, reference)
    if code != 0:
        fail(f"{task['id']} reference failed: {output}")
    print(f"{task['id']}: reference PASS")

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
    validate_crucible_spec(materialized)
    scan_public_package()
    for task in materialized:
        qualify_task(task)
    print("seam-agency-v0: package qualification PASS (2 references, 6 mutants)")


if __name__ == "__main__":
    main()
