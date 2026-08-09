"""Stage census tasks and run deterministic, provider-free probes."""
from __future__ import annotations
from dataclasses import replace

import importlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import re
from typing import Mapping
import tomllib


from harness_census_archive import archive_git_tree
from harness_census_common import (
    AGENT_ALLOWED_HOSTS, BUN_VERSION, CARGO_VERSION, CAMPAIGN_ID, CONTROLLED_EFFORT, CONTROLLED_MODEL,
    CONTROLLED_NETWORK_ENFORCEMENT, CONTROLLED_NETWORK_MODE, CONTROLLED_TASK_NETWORK_ENFORCEMENT,
    CONTROLLED_TRANSPORT_NETWORK_MODE, DECISION_POLICY, GO_VERSION, HARBOR_VERSION, HARNESSES, NATIVE_NETWORK_ENFORCEMENT,
    NATIVE_NETWORK_MODE, NATIVE_TASK_NETWORK_ENFORCEMENT, NATIVE_TRANSPORT_NETWORK_MODE, RETRY_POLICY, RUST_VERSION,
    Cell, Task, TaskRecord, bytes_digest, campaign_matrix, cell_stage_digest, cell_summary,
    canonical_task_set_digest, cohort_identity, confined_path, digest, fail, file_digest, harbor_reward_value, harness_catalog_digest,
    load_tasks, mcp_identity_digest, model_roster_digest, qualification_harness_records, reference_hunk_map_digest, row_identity, task_corpus_identity,
    task_identity, tree_digest, tree_files, verified_commit, worker_image_tag, write_json,
)
from harness_census_gateway import MINT_INTERNAL_BASE_URL, gateway_identity, validate_gateway_contract, write_gateway_assets
from harness_census_generation import dockerfile, harness_package_info, stage_prime_package, verifier_source
from harness_census_resume import staged_bytes_digest

QUALIFIER = Path(__file__).resolve().with_name("qualify_harness_census.py")
PACKAGE = Path(__file__).resolve().parents[1] / "benchmarks" / "harness-census-v0"
ROOT = PACKAGE.parents[1]
def ensure_clean_bench_source() -> None:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain=v1", "--untracked-files=all", "--", "scripts", "benchmarks/harness-census-v0"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        fail(f"Bench source status probe failed: {(result.stderr or result.stdout).strip()}")
    dirty = [line[3:] if len(line) >= 4 else line for line in result.stdout.splitlines() if line.strip()]
    if dirty:
        fail(f"Bench source bytes are dirty before stage manifest creation: {', '.join(dirty)}")


def _valid_digest(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)

def _smoke_identity() -> dict[str, object]:
    tasks = load_tasks()
    receipts: dict[str, dict[str, object]] = {}
    for task_id in tasks:
        path = PACKAGE / "receipts" / f"{task_id}.json"
        if not path.is_file():
            fail(f"smoke receipt is missing: {task_id}")
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if receipt.get("task_id") != task_id or receipt.get("qualified") is not True:
            fail(f"smoke receipt is invalid: {task_id}")
        if receipt.get("reference_hunk_map_digest") != reference_hunk_map_digest(tasks[task_id]):
            fail(f"smoke receipt hunk mapping is stale: {task_id}")
        receipts[task_id] = receipt
    task_digest = digest([
        task_identity(
            task,
            str(receipts[task.id]["fixture"]["tree_digest"]),
            file_digest(task.task_dir / "instruction.md"),
            file_digest(task.task_dir / "task.toml"),
            file_digest(task.task_dir / "grader.py"),
            file_digest(task.task_dir / "reference.patch"),
            reference_hunk_map_digest(task),
        )
        for task in tasks.values()
    ])
    pack_manifest = json.loads((PACKAGE / "compositions" / "digests.json").read_text(encoding="utf-8"))
    pack = {name: pack_manifest[name] for name in ("controlled_raw", "controlled_enriched")}
    gateway = gateway_identity()
    return {
        "roster_digest": model_roster_digest(),
        "catalog_digest": harness_catalog_digest(),
        "adapter_digest": digest([entry["adapter"] for entry in qualification_harness_records()]),
        "pack_digest": digest(pack),
        "mcp_digest": mcp_identity_digest(),
        "task_digest": task_digest,
        "reference_hunk_map_digest": digest([reference_hunk_map_digest(task) for task in tasks.values()]),
        "grader_digest": digest([receipts[task_id]["reference"]["grader_digest"] for task_id in tasks]),
        "gateway_digests": [gateway["gateway_digest"]],
        "gateway_dockerfile_digests": [gateway["gateway_dockerfile_digest"]],
        "compose_digests": [gateway["compose_digest"]],
    }


def validate_stage_manifest(stage: object, *, stage_id: str) -> None:
    if not isinstance(stage, dict):
        fail(f"{stage_id} stage manifest must be an object")
    schema = json.loads((PACKAGE / "schemas" / "stage-manifest-v1.schema.json").read_text(encoding="utf-8"))
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    missing = sorted(required - set(stage))
    unknown = sorted(set(stage) - set(properties))
    if missing or unknown:
        fail(f"{stage_id} stage manifest keys are invalid: missing={missing} unknown={unknown}")
    for key, rule in properties.items():
        if isinstance(rule, dict) and "const" in rule and key in stage and stage[key] != rule["const"]:
            fail(f"{stage_id} stage manifest field is invalid: {key}")
    if stage.get("campaign_id") != CAMPAIGN_ID or stage.get("stage_id") != stage_id:
        fail(f"{stage_id} stage manifest identity is invalid")
    if stage_id == "campaign" and not _valid_digest(stage.get("worker_preflight_digest")):
        fail("campaign stage manifest worker preflight digest is invalid")
    if stage_id == "campaign":
        cells = stage.get("cells")
        expected_cells = {str(row["cell_id"]) for row in campaign_matrix()}
        if not isinstance(cells, dict) or set(cells) != expected_cells:
            fail("campaign stage manifest cells are incomplete or undeclared")
        for cell_id, entry in cells.items():
            if not isinstance(entry, dict) or not isinstance(entry.get("summary"), dict) or entry["summary"].get("cell_id") != cell_id:
                fail(f"campaign stage manifest cell summary is invalid: {cell_id}")
            summary = entry["summary"]
            for key in ("agent_kwargs_digest", "agent_allowed_hosts_digest", "composition_digest", "adapter_digest", "mcp_digest"):
                if not _valid_digest(summary.get(key)):
                    fail(f"campaign stage manifest cell summary digest is invalid: {cell_id} {key}")
            tasks = entry.get("tasks")
            if not isinstance(tasks, list) or len(tasks) != len(load_tasks()):
                fail(f"campaign stage manifest task set is invalid: {cell_id}")
            for task in tasks:
                required_task_fields = ("task_id", "task_digest", "comparison_task_digest", "reference_hunk_map_digest", "source_cluster", "dockerfile_digest", "gateway_digest", "gateway_dockerfile_digest", "compose_digest", "grader_digest")
                if not isinstance(task, dict) or any(not isinstance(task.get(key), str) or not task[key] for key in required_task_fields):
                    fail(f"campaign stage manifest task identity is invalid: {cell_id}")
    for key in ("roster_digest", "catalog_digest", "adapter_digest", "pack_digest", "mcp_digest", "task_digest", "reference_hunk_map_digest", "grader_digest", "profile_digest"):
        if not _valid_digest(stage.get(key)):
            fail(f"{stage_id} stage manifest digest is invalid: {key}")
    for key in ("crucible_binary_digest", "prime_package_digest"):
        if stage.get(key) is not None and not _valid_digest(stage.get(key)):
            fail(f"{stage_id} stage manifest digest is invalid: {key}")
    for key in ("dockerfile_digests", "gateway_digests", "gateway_dockerfile_digests", "compose_digests", "package_digests"):
        values = stage.get(key)
        if not isinstance(values, list) or any(not _valid_digest(value) for value in values):
            fail(f"{stage_id} stage manifest digest list is invalid: {key}")
    probe = stage.get("controlled_tool_surface_probe")
    if probe is not None and (not isinstance(probe, dict) or probe.get("status") != "passed" or probe.get("task_network") != "denied_by_tool_and_sandbox" or not isinstance(probe.get("adapters"), list) or len(probe["adapters"]) < 3):
        fail(f"{stage_id} controlled tool surface probe is invalid")
    expected_network = {
        "transport_network_mode": {"controlled": CONTROLLED_TRANSPORT_NETWORK_MODE, "native_default": NATIVE_TRANSPORT_NETWORK_MODE},
        "network_enforcement": {"controlled": CONTROLLED_NETWORK_ENFORCEMENT, "native_default": NATIVE_NETWORK_ENFORCEMENT},
        "task_network_enforcement": {"controlled": CONTROLLED_TASK_NETWORK_ENFORCEMENT, "native_default": NATIVE_TASK_NETWORK_ENFORCEMENT},
    }
    for field, expected in expected_network.items():
        if stage.get(field) != expected:
            fail(f"{stage_id} stage manifest network contract is stale: {field}")
        schema_network = properties[field].get("properties", {})
        if {name: schema_network[name].get("const") for name in expected} != expected:
            fail(f"stage manifest schema network contract is stale: {field}")
    if stage.get("retry_policy") != RETRY_POLICY:
        fail(f"{stage_id} stage manifest retry policy is invalid")
    decision = stage.get("decision_policy")
    if not isinstance(decision, dict) or any(decision.get(key) != value for key, value in DECISION_POLICY.items()):
        fail(f"{stage_id} stage manifest decision policy is invalid")
    if stage_id == "smoke" and any(stage.get(key) != value for key, value in _smoke_identity().items()):
        fail("smoke stage manifest identity is stale")




def require_dir(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_dir():
        fail(f"{label} is missing: {resolved}")
    return resolved


def source_repo(source_root: Path, task: Task) -> Path:
    repository = task.source_repository.rsplit("/", 1)[-1]
    return require_dir(source_root / repository, f"source repository {repository}")


def qualification(source_root: Path) -> None:
    result = subprocess.run([sys.executable, str(QUALIFIER), "--no-smoke", "--source-root", str(source_root)], cwd=QUALIFIER.parent.parent, text=True, capture_output=True, check=False)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip().splitlines()[-1:]
        fail(f"qualification failed: {' '.join(detail)}")


def crucible_identity(path: Path) -> dict[str, str]:
    import re
    result = subprocess.run([str(path), "--version"], text=True, capture_output=True, check=False)
    if result.returncode:
        fail(f"Crucible version probe failed: {(result.stderr or result.stdout).strip()[-500:]}")
    commits = sorted(set(re.findall(r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])", result.stdout + result.stderr)))
    if len(commits) != 1:
        fail("Crucible version output must expose exactly one full commit")
    return {"commit": verified_commit(commits[0], "Crucible commit"), "binary_digest": bytes_digest(path.read_bytes())}


def load_compositions() -> tuple[dict[str, str], dict[str, str]]:
    assets: dict[str, str] = {}
    digests: dict[str, str] = {}
    manifest = json.loads((PACKAGE / "compositions" / "digests.json").read_text(encoding="utf-8"))
    for name in ("controlled_raw", "controlled_enriched"):
        declaration = manifest[name]
        if name == "controlled_enriched" and declaration.get("kind") == "generated_context_pack":
            assets[name] = "generated context pack"
            digests[name] = digest(declaration)
            continue
        path = PACKAGE / "compositions" / declaration["path"]
        actual = file_digest(path)
        if actual != declaration["sha256"]:
            fail(f"composition digest mismatch: {name}")
        assets[name], digests[name] = path.read_text(encoding="utf-8"), actual
    if not assets["controlled_raw"].strip():
        fail("controlled raw composition asset must not be empty")
    return assets, digests


def validate_smoke() -> dict[str, str]:
    path = PACKAGE / "smoke" / "harness-census-v0.json"
    smoke = json.loads(path.read_text(encoding="utf-8"))
    if smoke.get("schema_version") != "harness_census.smoke.v1" or smoke.get("kind") != "staging_manifest" or smoke.get("runnable") is not False:
        fail("smoke artifact is not an explicit non-runnable staging manifest")
    identity = _smoke_identity()
    for key in ("task_digest", "reference_hunk_map_digest", "grader_digest", "pack_digest"):
        if smoke.get(key) != identity[key]:
            fail(f"smoke identity is stale: {key}")
    tasks = load_tasks()
    if smoke.get("task_ids") != list(tasks) or "runner" in smoke or "model" in smoke:
        fail("smoke artifact has an invalid shared runner or task identity")
    cells = smoke.get("cells")
    expected = []
    for row in campaign_matrix():
        expected.append({**row, "task_ids": list(tasks), "identity_digest": digest({"cell": row, "task_digest": identity["task_digest"], "reference_hunk_map_digest": identity["reference_hunk_map_digest"]})})
    if cells != expected:
        fail("smoke cells do not match the canonical nine-cell matrix")
    stage_path = PACKAGE / "smoke" / "stage-manifest.json"
    validate_stage_manifest(json.loads(stage_path.read_text(encoding="utf-8")), stage_id="smoke")
    return {"smoke_digest": bytes_digest(path.read_bytes())}


def task_prompt(task: Task, composition: str, assets: Mapping[str, str], *, context_pack: object | None = None) -> str:
    prompt = (task.task_dir / "instruction.md").read_text(encoding="utf-8").strip()
    if composition == "native_default":
        return prompt + "\n"
    value = prompt + "\n\n" + assets["controlled_raw"].strip()
    if composition == "controlled_enriched":
        if context_pack is None:
            fail("controlled_enriched staging requires its generated context pack")
        value += "\n\n" + getattr(context_pack, "context_bytes").decode("utf-8")
    return value + "\n"


def staged_task_toml(task: Task, composition: str, worker_image: str) -> tuple[str, str]:
    text = (task.task_dir / "task.toml").read_text(encoding="utf-8")
    expected = "public"
    if "network_mode = \"public\"" not in text:
        fail(f"task manifest must declare Harbor public baseline: {task.id}")
    parsed = tomllib.loads(text)
    if parsed.get("environment", {}).get("network_mode") != expected:
        fail(f"task manifest baseline network mode is invalid: {task.id}")
    if parsed.get("environment", {}).get("docker_image") is not None:
        fail(f"task manifest must not predeclare worker image: {task.id}")
    if "[verifier]\n" not in text:
        fail(f"task manifest must declare a verifier section: {task.id}")
    staged = text.replace("[verifier]\n", "[verifier]\nenvironment_mode = \"separate\"\n", 1)
    staged = staged.rstrip() + f'\ndocker_image = "{worker_image}"\n\n[verifier.environment]\ndocker_image = "{worker_image}"\nnetwork_mode = "none"\n'
    staged_parsed = tomllib.loads(staged)
    verifier = staged_parsed.get("verifier", {})
    verifier_environment = verifier.get("environment", {})
    if verifier.get("environment_mode") != "separate" or verifier_environment.get("docker_image") != worker_image or verifier_environment.get("network_mode") != "none":
        fail(f"staged verifier isolation is invalid: {task.id}")
    return staged, expected

def stage_task(cell_dir: Path, task: Task, harness: str, composition: str, assets: Mapping[str, str], source_root: Path, package: dict[str, str]) -> TaskRecord:
    from harness_census_context import prepare_task_pack, raw_skill_digest

    task_dir = cell_dir / "tasks" / task.id
    env, source = task_dir / "environment", task_dir / "environment" / "repo"
    reference_bytes = (task.task_dir / "reference.patch").read_bytes()
    forbidden_tokens = [
        reference_bytes,
        *[task_id.encode("utf-8") for task_id in load_tasks() if task_id != task.id],
    ]
    archive_git_tree(source_repo(source_root, task), task.source_sha, source)
    forbidden_tokens.extend(line.strip()[1:] for line in reference_bytes.splitlines() if line[:1] in {b"+", b"-"} and not line.startswith((b"+++", b"---", b"@@")) and len(line.strip()) >= 16)
    context_pack = prepare_task_pack(cell_dir.parents[1], task.id, source, task.source_repository, task.source_sha, task.allowed_paths, source_root / "omp-config", forbidden_tokens)
    instruction = task_prompt(task, composition, assets, context_pack=context_pack)
    instruction_path = task_dir / "instruction.md"
    instruction_path.parent.mkdir(parents=True, exist_ok=True)
    instruction_path.write_text(instruction, encoding="utf-8")
    root = cell_dir.parents[1]
    context_dir = root / "context"
    if composition == "controlled_enriched":
        context_manifest_digest = context_pack.manifest_digest
        context_pack_digest = context_pack.pack_digest
    else:
        empty_manifest = {"schema_version": "harness_census.context_manifest.v1", "includes": [], "holdouts": []}
        context_manifest_digest = digest(empty_manifest)
        context_pack_digest = bytes_digest(b"")
        target_manifest = context_dir / "manifests" / f"{context_manifest_digest}.json"
        target_pack = context_dir / "packs" / f"{context_pack_digest}.md"
        target_manifest.parent.mkdir(parents=True, exist_ok=True)
        target_pack.parent.mkdir(parents=True, exist_ok=True)
        if target_manifest.exists() and json.loads(target_manifest.read_text(encoding="utf-8")) != empty_manifest:
            fail(f"immutable context manifest changed: {target_manifest}")
        if not target_manifest.exists():
            write_json(target_manifest, empty_manifest)
        if target_pack.exists() and target_pack.read_bytes() != b"":
            fail(f"immutable context pack changed: {target_pack}")
        if not target_pack.exists():
            target_pack.write_bytes(b"")
    package_name = "prime-package" if harness == "prime" else "runtime-package"
    shutil.copytree(package["path"], env / package_name, symlinks=True, copy_function=lambda source, destination: Path(destination).hardlink_to(source))
    if harness == "prime":
        shutil.copytree(package["node_toolchain_path"], env / "runtime-package", symlinks=True, copy_function=lambda source, destination: Path(destination).hardlink_to(source))
    worker_image = worker_image_tag(harness, task.id)
    docker_text = dockerfile(harness, package_name, task.id)
    (env / "Dockerfile").write_text(docker_text, encoding="utf-8")
    task_toml, network_mode = staged_task_toml(task, composition, worker_image)
    (task_dir / "task.toml").write_text(task_toml, encoding="utf-8")
    gateway = write_gateway_assets(task_dir, worker_image=worker_image, allow_user_namespaces=harness == "prime")
    tests = task_dir / "tests"
    tests.mkdir(parents=True, exist_ok=True)
    source_manifest = {name: bytes_digest(value) for name, value in tree_files(source, exclude_git=False).items()}
    (tests / "verify.py").write_text(verifier_source(task.task_dir / "grader.py", source_manifest, task.allowed_paths), encoding="utf-8")
    (tests / "verify.py").chmod(0o755)
    (tests / "test.sh").write_text("#!/bin/sh\nset -eu\nlog_dir=${HARNESS_CENSUS_LOG_DIR:-/logs/verifier}\nexport HARNESS_CENSUS_LOG_DIR=\"$log_dir\"\nverifier=${HARNESS_CENSUS_VERIFIER:-/tests/verify.py}\nworkspace=${HARNESS_CENSUS_WORKSPACE:-/workspace}\nmkdir -p \"$log_dir\"\nchmod 0755 \"$log_dir\"\npython3 \"$verifier\" \"$workspace\"\n", encoding="utf-8")
    (tests / "test.sh").chmod(0o755)
    files = tree_files(task_dir, exclude_git=False)
    if any(any(token in name.split("/") for token in (".git", "grader.py", "reference.patch", "mutants")) for name in files if not name.startswith("environment/repo/")):
        fail(f"staged task leaks qualification material: {task.id}")
    source_digest = tree_digest(source, exclude_git=False)
    grader_digest = file_digest(task.task_dir / "grader.py")
    hunk_map_digest = reference_hunk_map_digest(task)
    comparison_task_digest = task_corpus_identity(task, source_digest, grader_digest, file_digest(task.task_dir / "reference.patch"), hunk_map_digest)
    task_digest = task_identity(task, source_digest, file_digest(instruction_path), file_digest(task_dir / "task.toml"), grader_digest, file_digest(task.task_dir / "reference.patch"), hunk_map_digest)
    skill_digest = context_pack.skill_digest if composition == "controlled_enriched" else raw_skill_digest()
    return TaskRecord(task.id, task.source_cluster, task_digest, comparison_task_digest, grader_digest, hunk_map_digest, bytes_digest(docker_text.encode()), gateway["gateway_digest"], gateway["gateway_dockerfile_digest"], gateway["compose_digest"], f"tasks/{task.id}", task.immutable_paths, network_mode, context_manifest_digest, context_pack_digest, skill_digest, file_digest(instruction_path), context_pack.skill_count if composition == "controlled_enriched" else 0)
def preflight_network_enforcement(cell: Cell) -> dict[str, object]:
    """Prove the staged Compose topology blocks direct worker egress."""
    record = cell.task_records[0]
    environment = cell.cell_dir / record.task_dir / "environment"
    compose_path = environment / "docker-compose.yaml"
    project = f"harness-census-preflight-{digest(str(environment))[:12]}"
    compose = ["docker", "compose", "--project-name", project, "--file", str(compose_path)]
    config = subprocess.run([*compose, "config", "--quiet"], text=True, capture_output=True, check=False)
    if config.returncode:
        detail = (config.stderr or config.stdout).strip().splitlines()[-1:]
        fail(f"Compose network preflight is invalid: {' '.join(detail)}")
    probe_source = """
const http = require("node:http");
const apiPath = "/proxy/https/openrouter.ai/api/v1";
const rejectedTargets = {
  raw_dot_host_escape: apiPath + "/../../../169.254.169.254/latest/meta-data",
  encoded_dot_host_escape: apiPath + "/%2e%2e/%2e%2e/%2e%2e/169.254.169.254/latest/meta-data",
  raw_slash: apiPath + "//models",
  encoded_slash: apiPath + "%2fmodels",
  raw_backslash: apiPath + "/" + String.fromCharCode(92) + "models",
  encoded_backslash: apiPath + "/%5cmodels",
  loopback_host_escape: apiPath + "/../../../127.0.0.1:80/",
  rfc1918_host_escape: apiPath + "/../../../192.168.0.1/",
};
function requestStatus(path, method = "GET", headers = {}) {
  return new Promise(resolve => {
    try {
      const request = http.request({ hostname: "mint-gateway", port: 4949, path, method, headers }, response => {
        response.resume();
        response.once("end", () => resolve(response.statusCode || 0));
      });
      request.once("error", () => resolve(0));
      request.setTimeout(3000, () => {
        request.destroy();
        resolve(0);
      });
      request.end();
    } catch {
      resolve(0);
    }
  });
}
(async () => {
  const directBlocked = await fetch("http://1.1.1.1", {
    signal: AbortSignal.timeout(3000),
  }).then(() => false, () => true);
  const gatewayStatus = await fetch("http://mint-gateway:4949/", {
    signal: AbortSignal.timeout(3000),
  }).then(response => response.status, () => 0);
  const targetStatuses = {};
  for (const [name, path] of Object.entries(rejectedTargets)) targetStatuses[name] = await requestStatus(path);
  const methodStatus = await requestStatus(apiPath, "DELETE");
  const wrongPathStatus = await requestStatus("/");
  const upgradeStatus = await requestStatus(apiPath, "GET", { Connection: "Upgrade", Upgrade: "websocket" });
  const allTargetsRejected = Object.values(targetStatuses).every(status => status === 404);
  if (!directBlocked || gatewayStatus !== 404 || !allTargetsRejected || methodStatus !== 405 || wrongPathStatus !== 404 || upgradeStatus !== 400) process.exit(1);
})().catch(() => process.exit(1));
"""
    failure: str | None = None
    try:
        start = subprocess.run([*compose, "up", "--build", "--detach", "--wait", "--wait-timeout", "30", "mint-gateway"], text=True, capture_output=True, check=False)
        if start.returncode:
            failure = " ".join((start.stderr or start.stdout).strip().splitlines()[-1:])
        else:
            probe = subprocess.run(
                [*compose, "run", "--build", "--rm", "--no-deps", "--entrypoint", "node", "main", "-e", probe_source],
                text=True,
                capture_output=True,
                check=False,
            )
            if probe.returncode:
                failure = " ".join((probe.stderr or probe.stdout).strip().splitlines()[-1:])
    finally:
        subprocess.run([*compose, "down", "--volumes", "--remove-orphans", "--rmi", "local"], text=True, capture_output=True, check=False)
    if failure is not None:
        fail(f"Compose network enforcement preflight failed: {failure}")
    return {
        "status": "passed",
        "worker_direct_egress": "blocked",
        "gateway_reachable": True,
        "gateway_service": "mint-gateway",
        "gateway_path_rejection": True,
        "gateway_path_rejection_probes": [
            "raw_dot_host_escape",
            "encoded_dot_host_escape",
            "raw_slash",
            "encoded_slash",
            "raw_backslash",
            "encoded_backslash",
            "loopback_host_escape",
            "rfc1918_host_escape",
            "wrong_path",
        ],
        "gateway_method_rejection": True,
        "gateway_upgrade_rejection": True,
        "gateway_port": 4949,
    }


def preflight_worker_images(root: Path, cells: tuple[Cell, ...]) -> dict[str, object]:
    """Build every harness/task image and run its hidden reference grader inside it."""
    if not shutil.which("docker"):
        fail("worker image preflight requires docker before provider calls")
    tasks = load_tasks()
    representatives = {
        harness: next(cell for cell in cells if cell.harness == harness and cell.composition == "native_default")
        for harness in HARNESSES
    }
    results: list[dict[str, object]] = []
    command = (
        "set -eu; test ! -e /workspace/grader.py && test ! -e /workspace/reference.patch && test ! -e /tests/verify.py; "
        "mkdir -p /tmp/home /tmp/go-cache /tmp/cargo-target /tmp/bun-cache; "
        "rm -rf /tmp/reference-repo /tmp/grader-output; cp -a /workspace /tmp/reference-repo; "
        "patch --batch --forward -p1 -d /tmp/reference-repo < /qualification/reference.patch; "
        "set +e; python3 /qualification/grader.py /tmp/reference-repo > /tmp/grader-output; grader_rc=$?; set -e; "
        "python3 - /tmp/grader-output /preflight/reward.json \"$grader_rc\" <<'PY'\n"
        "import json, pathlib, sys\n"
        "lines = [line for line in pathlib.Path(sys.argv[1]).read_text(encoding='utf-8').splitlines() if line.strip()]\n"
        "report = json.loads(lines[-1]) if lines else {}\n"
        "reward = 1.0 if int(sys.argv[3]) == 0 and report.get('passed') is True else 0.0\n"
        "pathlib.Path(sys.argv[2]).write_text(json.dumps({'reward': reward}) + '\\n', encoding='utf-8')\n"
        "print(json.dumps({'reward': reward, 'report': report}, sort_keys=True))\n"
        "raise SystemExit(0 if reward == 1.0 else 1)\n"
        "PY"
    )
    prime_sandbox_args = (
        "bwrap", "--die-with-parent", "--unshare-user", "--uid", "0", "--gid", "0", "--unshare-net",
        "--proc", "/proc", "--dev", "/dev", "--ro-bind", "/usr", "/usr", "--ro-bind", "/bin", "/bin",
        "--ro-bind", "/lib", "/lib", "--ro-bind", "/lib64", "/lib64", "/usr/bin/true",
    )
    with tempfile.TemporaryDirectory(prefix="harness-census-preflight-") as temporary:
        workspace = Path(temporary)
        for harness, representative in sorted(representatives.items()):
            for task_id, task in tasks.items():
                task_root = representative.cell_dir / next(record.task_dir for record in representative.task_records if record.task_id == task_id)
                environment = task_root / "environment"
                context = workspace / f"{harness}-{task_id}"
                shutil.copytree(environment / "repo", context / "repo", symlinks=True)
                package_name = "prime-package" if harness == "prime" else "runtime-package"
                shutil.copytree(environment / package_name, context / package_name, symlinks=True)
                if harness == "prime":
                    shutil.copytree(environment / "runtime-package", context / "runtime-package", symlinks=True)
                (context / "Dockerfile").write_text(dockerfile(harness, package_name, task_id), encoding="utf-8")
                tag = worker_image_tag(harness, task_id)
                build = subprocess.run(
                    ["docker", "build", "--pull=false", "--tag", tag, str(context)],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if build.returncode:
                    detail = (build.stderr or build.stdout).strip().splitlines()[-1:]
                    fail(f"{harness}/{task_id} worker image build failed: {' '.join(detail)}")
                output = workspace / f"{harness}-{task_id}-result"
                output.mkdir()
                mounts = [
                    f"{task.task_dir / 'reference.patch'}:/qualification/reference.patch:ro",
                    f"{task.task_dir / 'grader.py'}:/qualification/grader.py:ro",
                    f"{output}:/preflight:rw",
                ]
                if harness == "prime":
                    sandbox = subprocess.run(
                        [
                            "docker", "run", "--rm", "--network", "none", "--read-only",
                            "--security-opt", "seccomp=unconfined",
                            "--tmpfs", "/tmp:rw,exec,nosuid,nodev", tag, *prime_sandbox_args,
                        ],
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    if sandbox.returncode:
                        detail = (sandbox.stderr or sandbox.stdout).strip().splitlines()[-1:]
                        fail(f"{harness}/{task_id} inner sandbox preflight failed: {' '.join(detail)}")
                run = subprocess.run(
                    [
                        "docker", "run", "--rm", "--network", "none", "--read-only",
                        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                        "--tmpfs", "/tmp:rw,exec,nosuid,nodev",
                        *sum((["--volume", mount] for mount in mounts), []),
                        "--env", "HOME=/tmp/home", "--env", "GOCACHE=/tmp/go-cache",
                        "--env", "CARGO_TARGET_DIR=/tmp/cargo-target", "--env", "BUN_INSTALL_CACHE_DIR=/tmp/bun-cache",
                        "--entrypoint", "/bin/sh", tag, "-c", command,
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                reward_path = output / "reward.json"
                if run.returncode or not reward_path.is_file():
                    detail = (run.stderr or run.stdout).strip().splitlines()[-1:]
                    fail(f"{harness}/{task_id} in-image grader failed: {' '.join(detail)}")
                reward = harbor_reward_value(json.loads(reward_path.read_text(encoding="utf-8")))
                if reward != 1.0:
                    fail(f"{harness}/{task_id} preflight reward is not 1.0: {reward!r}")
                inspect = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", tag], text=True, capture_output=True, check=False)
                image_id = inspect.stdout.strip()
                if inspect.returncode or not image_id.startswith("sha256:"):
                    fail(f"{harness}/{task_id} worker image identity is unavailable")
                results.append({"harness": harness, "task_id": task_id, "reward": reward, "sandbox": "bwrap-user-net" if harness == "prime" else "container", "image_tag": tag, "image_id": image_id})
    network_report = preflight_network_enforcement(representatives["prime"])
    report = {
        "status": "passed",
        "network": "none",
        "filesystem": "read-only-root-tmpfs-tmp",
        "toolchains": {"go": GO_VERSION, "rustc": RUST_VERSION, "cargo": CARGO_VERSION, "bun": BUN_VERSION, "pnpm": "10.22.0"},
        "prime_inner_sandbox": "bwrap-user-net",
        "checks": len(results),
        "results": results,
        "network_enforcement": network_report,
    }
    if len(results) != 9:
        fail(f"worker preflight checked {len(results)} images, expected 9")
    write_json(root / "worker-preflight.json", report)
    return report

def verify_worker_images(root: Path, cells: tuple[Cell, ...], report: dict[str, object]) -> None:
    if not shutil.which("docker"):
        fail("worker image verification requires docker before provider calls")
    entries = {(item.get("harness"), item.get("task_id")): item for item in report.get("results", []) if isinstance(item, dict)}
    for cell in cells:
        for record in cell.task_records:
            key = (cell.harness, record.task_id)
            entry = entries.get(key)
            tag = worker_image_tag(cell.harness, record.task_id)
            if not isinstance(entry, dict) or entry.get("image_tag") != tag or not isinstance(entry.get("image_id"), str):
                fail(f"worker preflight is missing image identity: {cell.harness}/{record.task_id}")
            inspect = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", tag], text=True, capture_output=True, check=False)
            if inspect.returncode or inspect.stdout.strip() != entry["image_id"]:
                fail(f"worker image tag drifted: {tag}")
            task_dir = cell.cell_dir / record.task_dir
            task_config = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
            if task_config.get("environment", {}).get("docker_image") != tag or task_config.get("verifier", {}).get("environment", {}).get("docker_image") != tag:
                fail(f"staged worker image tag mismatch: {cell.cell_id}/{record.task_id}")
            compose = (task_dir / "environment/docker-compose.yaml").read_text(encoding="utf-8")
            if f"    image: {tag}\n" not in compose or "    build:\n      context: .\n      dockerfile: Dockerfile" in compose:
                fail(f"staged Compose worker image is not frozen: {cell.cell_id}/{record.task_id}")

def probe_harbor_task_validity(cells: tuple[Cell, ...]) -> dict[str, object]:
    task_paths = sorted({cell.cell_dir / record.task_dir for cell in cells for record in cell.task_records}, key=str)
    task_ids = {path.name for path in task_paths}
    controlled = [record for cell in cells if cell.cell_kind == "controlled" for record in cell.task_records]
    if not controlled or {record.network_mode for record in controlled} != {CONTROLLED_NETWORK_MODE}:
        fail("controlled staged tasks do not use configured task network mode")
    if task_ids != set(load_tasks()):
        fail(f"staged Harbor task set is invalid: {sorted(task_ids)}")
    for cell in cells:
        spec_config = json.loads(cell.spec_path.read_text(encoding="utf-8"))["runner"]["corpus"]["config"]
        if spec_config.get("agent_allowed_hosts") != ["mint-gateway"]:
            fail(f"Harbor command config host allowlist is invalid: {cell.cell_id}")
    for task_path in task_paths:
        task_config = tomllib.loads((task_path / "task.toml").read_text(encoding="utf-8"))
        verifier = task_config.get("verifier", {})
        environment = task_config.get("environment", {})
        verifier_environment = verifier.get("environment", {})
        if verifier.get("environment_mode") != "separate" or environment.get("docker_image") != verifier_environment.get("docker_image") or verifier_environment.get("network_mode") != "none":
            fail(f"Harbor verifier isolation is invalid: {task_path.name}")
    check = """from pathlib import Path
import sys
from harbor.models.task.task import Task
paths = [Path(value) for value in sys.argv[1:]]
invalid = [str(path) for path in paths if not Task.is_valid_dir(path)]
if invalid:
    print("invalid staged tasks: " + ", ".join(invalid), file=sys.stderr)
    raise SystemExit(1)
print(f"Harbor 0.13.1 valid staged tasks={len(paths)}")
"""
    try:
        from harness_census_exchange import safe_runtime_environment

        result = subprocess.run(["uvx", "--from", f"harbor=={HARBOR_VERSION}", "python", "-c", check, *map(str, task_paths)], env=safe_runtime_environment(), text=True, capture_output=True, check=False)
    except OSError as error:
        fail(f"Harbor {HARBOR_VERSION} staged task validity probe could not start: {error}")
    if result.returncode:
        detail = (result.stderr or result.stdout).strip().splitlines()[-1:]
        fail(f"Harbor {HARBOR_VERSION} staged task validity failed: {' '.join(detail)}")
    return {"version": HARBOR_VERSION, "task_count": len(task_paths), "task_ids": sorted(task_ids), "all_valid": True, "controlled_task_count": len(controlled), "transport_network_mode": CONTROLLED_TRANSPORT_NETWORK_MODE, "task_network_enforcement": CONTROLLED_TASK_NETWORK_ENFORCEMENT}


def copy_adapters(campaign_root: Path, adapter_root: Path) -> str:
    source = adapter_root / "harbor_agents" if adapter_root.name != "harbor_agents" and (adapter_root / "harbor_agents").is_dir() else adapter_root
    if not source.is_dir():
        fail(f"pinned harbor_agents package is missing: {source}")
    destination = campaign_root / "cells" / "harbor_agents"
    shutil.copytree(source, destination)
    required = {"__init__.py", "prime_agent.py", "prime_kernel_wrapper.sh", "omp_agent.py", "pi_agent.py"}
    if not required.issubset(path.name for path in destination.iterdir()):
        fail("pinned harbor_agents package is incomplete")
    return tree_digest(destination, exclude_git=False)


def probe_controlled_argv_surfaces(adapter_root: Path) -> dict[str, object]:
    source = adapter_root / "harbor_agents" if adapter_root.name != "harbor_agents" and (adapter_root / "harbor_agents").is_dir() else adapter_root
    common_path = source / "adapter_common.py"
    if not common_path.is_file():
        fail(f"adapter command contract is missing: {common_path}")
    package_parent = str(source.parent)
    sys.path.insert(0, package_parent)
    try:
        module = importlib.import_module("harbor_agents.adapter_common")
    except (ImportError, OSError) as error:
        fail(f"adapter command contract cannot load: {common_path}: {error}")
    finally:
        sys.path.remove(package_parent)
    build_argv = getattr(module, "build_argv", None)
    if not callable(build_argv):
        fail("adapter command contract does not expose build_argv")
    wrapper_path = source / "prime_kernel_wrapper.sh"
    wrapper = wrapper_path.read_text(encoding="utf-8") if wrapper_path.is_file() else ""
    if "env -i" not in wrapper or "--unshare-net" not in wrapper:
        fail("Prime IPython wrapper does not clear ambient credentials and deny network")
    prime_guard = {"kind": "bwrap_unshare_net_clean_env", "digest": file_digest(wrapper_path)}
    expected_tools = {"prime": "ipython", "omp": "read,edit,write", "pi": "read,edit,write"}
    required_flags = {"prime": ("--no-context-files", "--no-extensions", "--no-prompt-templates", "--no-skills", "--no-themes"), "omp": ("--no-extensions", "--no-rules", "--no-skills"), "pi": ("--no-context-files", "--no-extensions", "--no-prompt-templates", "--no-skills", "--no-themes")}
    enabled_context_flags = {"--context", "--context-file", "--extension", "--extensions", "--mcp", "--rule", "--rules", "--skill", "--skills", "--theme", "--themes", "--prompt-template", "--prompt-templates"}
    records: list[dict[str, object]] = []
    for name in HARNESSES:
        command = list(build_argv(name, composition="controlled_raw", provider="openrouter", model="probe", thinking=CONTROLLED_EFFORT, instruction="controlled-probe", profile="harness-census-probe"))
        if any(marker in token.lower() for token in command for marker in ("shell", "process", "browser", "mcp")) or any(token in enabled_context_flags for token in command) or any(flag not in command for flag in required_flags[name]):
            fail(f"controlled {name} argv exposes an undeclared surface: {command}")
        try:
            tools = command[command.index("--tools") + 1]
        except (ValueError, IndexError):
            fail(f"controlled {name} argv has no declared tool surface: {command}")
        if tools != expected_tools[name]:
            fail(f"controlled {name} argv tool surface is {tools!r}, expected {expected_tools[name]!r}")
        record: dict[str, object] = {"adapter": name, "tool_surface": tools, "argv_digest": digest(command), "context_flags": list(required_flags[name])}
        if name == "prime":
            record["tool_network_guard"] = prime_guard
        records.append(record)
    return {"status": "passed", "task_network": "denied_by_tool_and_sandbox", "adapters": records}




def immutable_stage_cells(cells: tuple[Cell, ...]) -> dict[str, object]:
    tasks = load_tasks()
    return {
        cell.cell_id: {
            "summary": cell_summary(cell),
            "tasks": [
                {
                    "task_id": record.task_id,
                    "task_digest": record.task_digest,
                    "comparison_task_digest": record.comparison_task_digest,
                    "reference_hunk_map_digest": record.reference_hunk_map_digest,
                    "source_cluster": record.source_cluster,
                    "dockerfile_digest": record.dockerfile_digest,
                    "gateway_digest": record.gateway_digest,
                    "gateway_dockerfile_digest": record.gateway_dockerfile_digest,
                    "compose_digest": record.compose_digest,
                    "grader_digest": record.grader_digest,
                    "context_manifest_digest": record.context_manifest_digest,
                    "context_pack_digest": record.context_pack_digest,
                    "context_digest": record.context_digest,
                    "skill_digest": record.skill_digest,
                    "skill_count": record.skill_count,
                }
                for record in cell.task_records
            ],
        }
        for cell in cells
    }

def build_cells(root: Path, assets: Mapping[str, str], composition_digests: Mapping[str, str], source_root: Path, adapter_root: Path, prime_package: dict[str, str] | None) -> tuple[Cell, ...]:
    validate_gateway_contract()
    tasks = load_tasks()
    adapter_digest = copy_adapters(root, adapter_root)
    cells: list[Cell] = []
    packages = {harness: harness_package_info(harness, prime_package) for harness in HARNESSES}
    for row in campaign_matrix():
        harness, composition = str(row["harness"]), str(row["composition"])
        spec, package = HARNESSES[harness], packages[harness]
        cell_id, cell_dir = str(row["cell_id"]), root / "cells" / str(row["cell_id"])
        cell_dir.mkdir(parents=True, exist_ok=True)
        records = tuple(stage_task(cell_dir, tasks[task_id], harness, composition, assets, source_root, package) for task_id in tasks)
        task_digest = digest([record.task_digest for record in records])
        task_set = [(record.task_id, record.comparison_task_digest) for record in records]
        task_set_digest = canonical_task_set_digest(task_set)
        task_set_size = len(task_set)
        cell_run_id = f"{CAMPAIGN_ID}--{cell_id}"
        retry_policy_digest = digest(RETRY_POLICY)
        controlled = composition != "native_default"
        network_mode = CONTROLLED_NETWORK_MODE if controlled else NATIVE_NETWORK_MODE
        network_enforcement = CONTROLLED_NETWORK_ENFORCEMENT if controlled else NATIVE_NETWORK_ENFORCEMENT
        transport_mode = CONTROLLED_TRANSPORT_NETWORK_MODE if controlled else NATIVE_TRANSPORT_NETWORK_MODE
        task_enforcement = CONTROLLED_TASK_NETWORK_ENFORCEMENT if controlled else NATIVE_TASK_NETWORK_ENFORCEMENT
        allowed_hosts = AGENT_ALLOWED_HOSTS
        model, effort = row["model_requested"], row["effort_requested"]
        kwargs: Mapping[str, object] = {"composition": composition, "thinking": CONTROLLED_EFFORT, "mint_base_url": MINT_INTERNAL_BASE_URL} if controlled else {"composition": "native_default", "mint_base_url": MINT_INTERNAL_BASE_URL}
        agent_kwargs_base_digest = digest({key: value for key, value in kwargs.items() if key not in {"composition", "thinking", "reasoning_effort"}})
        config: dict[str, object] = {"agent": harness, "agent_import_path": spec.adapter, "job_timeout_ms": 900000, "agent_kwargs": dict(kwargs), "agent_allowed_hosts": list(allowed_hosts)}
        if controlled:
            config["model"] = CONTROLLED_MODEL
        spec_json = {"schema_version": "crucible.eval_spec.v1", "id": cell_id, "task": CAMPAIGN_ID, "inputs": "Three history-free pinned repository repair tasks with deterministic graders.", "outputs": "Harbor verifier reward per task.", "graders": {"graders": [{"id": "harness_census_deterministic", "kind": "deterministic"}]}, "aggregation": "proportion", "uncertainty": {"method": "wilson", "confidence": 0.95}, "decision": "Native defaults remain separate from controlled comparisons.", "runner": {"kind": "harbor_task", "corpus": {"source": "harbor_tasks", "config": config, "tasks": [{"task_id": record.task_id, "task_dir": record.task_dir} for record in records]}}}
        spec_path = cell_dir / "eval.json"
        write_json(spec_path, spec_json)
        gateway_digests = tuple(sorted({record.gateway_digest for record in records}))
        gateway_dockerfile_digests = tuple(sorted({record.gateway_dockerfile_digest for record in records}))
        compose_digests = tuple(sorted({record.compose_digest for record in records}))
        composition_identity = {"mint_base_url": MINT_INTERNAL_BASE_URL, "gateway_digests": list(gateway_digests), "gateway_dockerfile_digests": list(gateway_dockerfile_digests), "compose_digests": list(compose_digests)}
        if composition == "native_default":
            composition_digest = digest({"composition": composition, **composition_identity})
        elif composition == "controlled_raw":
            composition_digest = digest({"composition": composition, "restriction_digest": bytes_digest((assets["controlled_raw"].strip() + "\n").encode("utf-8")), "skill_digest": records[0].skill_digest, "skill_count": 0, **composition_identity})
        else:
            composition_digest = digest({"composition": composition, "context_manifest_digests": [record.context_manifest_digest for record in records], "context_pack_digests": [record.context_pack_digest for record in records], "skill_digest": records[0].skill_digest, "skill_count": records[0].skill_count, **composition_identity})
        docker_digests = tuple(sorted({record.dockerfile_digest for record in records}))
        package_digest = package["digest"]
        prime_digest = package["prime_digest"] if harness == "prime" else None
        row_id = row_identity(CONTROLLED_MODEL, CONTROLLED_EFFORT, harness, composition) if controlled else None
        cohort_id = cohort_identity(CONTROLLED_MODEL, CONTROLLED_EFFORT, CONTROLLED_MODEL, CONTROLLED_EFFORT) if controlled else None
        baseline_id = None
        profile = digest({"harness": harness, "version": spec.version, "adapter_digest": adapter_digest, "kwargs": kwargs, "task_digest": task_digest, "composition_digest": composition_digest, "package_digest": package_digest, "prime_package_digest": prime_digest, "dockerfile_digests": list(docker_digests), **composition_identity, "transport_network_mode": transport_mode, "network_enforcement": network_enforcement, "task_network_enforcement": task_enforcement})
        cells.append(
            Cell(
                cell_id=cell_id,
                cell_run_id=cell_run_id,
                task_set_digest=task_set_digest,
                task_set_size=task_set_size,
                retry_policy_digest=retry_policy_digest,
                agent_kwargs_base_digest=agent_kwargs_base_digest,
                cell_dir=cell_dir,
                spec_path=spec_path,
                cell_kind="controlled" if controlled else "native_default",
                harness=harness,
                harness_version=spec.version,
                composition=composition,
                model_requested=model if isinstance(model, str) else None,
                effort_requested=effort if isinstance(effort, str) else None,
                provider_route_resolved=model if isinstance(model, str) else None,
                provider_effort_resolved=effort if isinstance(effort, str) else None,
                default_resolution_source=None,
                effort_source="requested" if controlled else None,
                row_id=row_id,
                cohort_id=cohort_id,
                baseline_id=baseline_id,
                profile_digest=profile,
                agent_kwargs=kwargs,
                agent_allowed_hosts=tuple(allowed_hosts),
                network_mode=network_mode,
                transport_network_mode=transport_mode,
                network_enforcement=network_enforcement,
                task_network_enforcement=task_enforcement,
                task_digest=task_digest,
                composition_digest=composition_digest,
                adapter_digest=adapter_digest,
                package_digest=package_digest,
                dockerfile_digests=docker_digests,
                gateway_digests=gateway_digests,
                gateway_dockerfile_digests=gateway_dockerfile_digests,
                compose_digests=compose_digests,
                task_records=records,
            )
        )
    if len(cells) != 9 or sum(len(cell.task_records) for cell in cells) != 27:
        fail("driver matrix is not exactly 9 cells and 27 trials")
    controlled = [cell for cell in cells if cell.cell_kind == "controlled"]
    if len({cell.row_id for cell in controlled}) != 6 or len({cell.cohort_id for cell in controlled}) != 1:
        fail("controlled rows are not unique and pairable")
    for cell in cells:
        config = json.loads(cell.spec_path.read_text(encoding="utf-8"))["runner"]["corpus"]["config"]
        spec = HARNESSES[cell.harness]
        if cell.cell_kind == "native_default":
            expected = {"agent": cell.harness, "agent_import_path": spec.adapter, "job_timeout_ms": 900000, "agent_kwargs": {"composition": "native_default", "mint_base_url": MINT_INTERNAL_BASE_URL}, "agent_allowed_hosts": ["mint-gateway"]}
            valid = config == expected and cell.network_mode == NATIVE_NETWORK_MODE and cell.transport_network_mode == NATIVE_TRANSPORT_NETWORK_MODE and cell.network_enforcement == NATIVE_NETWORK_ENFORCEMENT and cell.task_network_enforcement == NATIVE_TASK_NETWORK_ENFORCEMENT and cell.agent_allowed_hosts == AGENT_ALLOWED_HOSTS and cell.model_requested is None and cell.effort_requested is None and cell.provider_route_resolved is None and cell.provider_effort_resolved is None and cell.default_resolution_source is None
        else:
            expected = {"agent": cell.harness, "agent_import_path": spec.adapter, "job_timeout_ms": 900000, "model": CONTROLLED_MODEL, "agent_kwargs": {"composition": cell.composition, "thinking": CONTROLLED_EFFORT, "mint_base_url": MINT_INTERNAL_BASE_URL}, "agent_allowed_hosts": ["mint-gateway"]}
            valid = config == expected and cell.network_mode == CONTROLLED_NETWORK_MODE and cell.transport_network_mode == CONTROLLED_TRANSPORT_NETWORK_MODE and cell.network_enforcement == CONTROLLED_NETWORK_ENFORCEMENT and cell.task_network_enforcement == CONTROLLED_TASK_NETWORK_ENFORCEMENT and cell.agent_allowed_hosts == AGENT_ALLOWED_HOSTS and cell.model_requested == CONTROLLED_MODEL and cell.effort_requested == CONTROLLED_EFFORT and cell.provider_route_resolved == CONTROLLED_MODEL and cell.provider_effort_resolved == CONTROLLED_EFFORT
        if not valid:
            fail(f"staged config or metadata shape is invalid: {cell.cell_id}")
    return tuple(cells)


def write_harbor_wrapper(root: Path) -> Path:
    wrapper = confined_path(root, "bin", "harbor")
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text(f"#!/bin/sh\nset -eu\nexec uvx --from harbor=={HARBOR_VERSION} harbor \"$@\"\n", encoding="utf-8")
    wrapper.chmod(0o755)
    return wrapper


def read_verifier_result(log_dir: Path) -> tuple[float, dict[str, object]]:
    reward_path, report_path = log_dir / "reward.json", log_dir / "grader-report.json"
    if not reward_path.is_file() or not report_path.is_file():
        fail(f"staged verifier evidence is incomplete: {log_dir}")
    reward = harbor_reward_value(json.loads(reward_path.read_text(encoding="utf-8")))
    if reward is None:
        fail("Harbor reward.json must contain one canonical bounded reward map")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        fail(f"grader report is not an object: {report!r}")
    if report.get("task_points") != reward or not isinstance(report.get("hard_pass"), bool) or report.get("passed") != report.get("hard_pass"):
        fail(f"staged verifier score identity is invalid: {report!r}")
    return reward, report


def probe_verifier(root: Path, cell: Cell) -> dict[str, object]:
    task = cell.cell_dir / cell.task_records[0].task_dir
    log_dir = root / "probes" / cell.cell_id
    environment = {**os.environ, "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}", "HARNESS_CENSUS_LOG_DIR": str(log_dir), "HARNESS_CENSUS_VERIFIER": str(task / "tests" / "verify.py"), "HARNESS_CENSUS_WORKSPACE": str(task / "environment" / "repo")}
    result = subprocess.run([str(task / "tests" / "test.sh")], env=environment, text=True, capture_output=True, check=False)
    reward, report = read_verifier_result(log_dir)
    if report.get("status") != "quality_failure" or reward != 0.0:
        fail(f"unchanged staged task did not produce quality failure: {report}")
    return {"cell_id": cell.cell_id, "return_code": result.returncode, "status": report["status"], "reward": reward, "grader_report": report.get("grader_report")}


def run_scope_probes(root: Path, cell: Cell) -> dict[str, object]:
    record, task, source = cell.task_records[0], cell.cell_dir / cell.task_records[0].task_dir, cell.cell_dir / cell.task_records[0].task_dir / "environment" / "repo"
    with tempfile.TemporaryDirectory(prefix="harness-census-scope-") as temporary:
        scratch = Path(temporary)
        unrelated = scratch / "unrelated"
        shutil.copytree(source, unrelated, symlinks=True)
        immutable_file = unrelated / record.immutable_paths[0]
        immutable_file.write_bytes(immutable_file.read_bytes() + b"\nscope probe\n")
        bad_log = scratch / "bad-log"
        bad = subprocess.run([sys.executable, str(task / "tests" / "verify.py"), str(unrelated)], env={**os.environ, "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}", "HARNESS_CENSUS_LOG_DIR": str(bad_log)}, text=True, capture_output=True, check=False)
        _, bad_report = read_verifier_result(bad_log)
        if bad.returncode == 0 or bad_report.get("grader_report", {}).get("failed_check") != "scope":
            fail(f"unrelated scope probe did not fail scope: {bad_report}")
        allowed = scratch / "allowed"
        shutil.copytree(source, allowed, symlinks=True)
        patch = load_tasks()[record.task_id].task_dir / "reference.patch"
        checked = subprocess.run(["git", "-C", str(allowed), "apply", "--check", str(patch)], text=True, capture_output=True, check=False)
        if checked.returncode:
            fail(f"reference scope probe cannot apply: {checked.stderr.strip()}")
        applied = subprocess.run(["git", "-C", str(allowed), "apply", str(patch)], text=True, capture_output=True, check=False)
        if applied.returncode:
            fail(f"reference scope probe failed: {applied.stderr.strip()}")
        good_log = scratch / "good-log"
        good = subprocess.run([sys.executable, str(task / "tests" / "verify.py"), str(allowed)], env={**os.environ, "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}", "HARNESS_CENSUS_LOG_DIR": str(good_log)}, text=True, capture_output=True, check=False)
        good_reward, good_report = read_verifier_result(good_log)
        if good.returncode or good_report.get("status") != "success" or good_reward != 1.0:
            fail(f"reference scope probe did not pass quality and scope: {good_report}")
    return {"unrelated_mutation": {"passed": True, "status": bad_report["status"], "failed_check": bad_report["grader_report"]["failed_check"]}, "allowed_reference": {"passed": True, "status": good_report["status"], "reward": good_reward}}






def resume_staged_cells(root: Path, source_root: Path, adapter_root: Path, prime_source: Path) -> tuple[tuple[Cell, ...], dict[str, str], dict[str, str], dict[str, str]]:
    assets, composition_digests = load_compositions()
    with tempfile.TemporaryDirectory(prefix="harness-census-resume-") as temporary:
        staged = Path(temporary)
        prime_package = stage_prime_package(staged, prime_source)
        expected = build_cells(staged, assets, composition_digests, source_root, adapter_root, prime_package)
        write_json(staged / "prime-package.json", {key: prime_package[key] for key in ("package", "version", "source_kind", "digest")})
        write_harbor_wrapper(staged)
        expected_digest = staged_bytes_digest(staged)
        expected_cell_digests = {cell.cell_id: cell_stage_digest(cell.cell_dir, include_workspace=False) for cell in expected}
    if staged_bytes_digest(root) != expected_digest:
        fail("immutable staged bytes do not match the frozen campaign")
    cells = tuple(replace(cell, cell_dir=root / "cells" / cell.cell_id, spec_path=root / "cells" / cell.cell_id / "eval.json") for cell in expected)
    return cells, composition_digests, prime_package, expected_cell_digests
