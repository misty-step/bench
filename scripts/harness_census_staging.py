"""Stage census tasks and run deterministic, provider-free probes."""
from __future__ import annotations

import base64
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Mapping

from harness_census_archive import archive_git_tree
from harness_census_common import (
    AGENT_ALLOWED_HOSTS, BUN_VERSION, CAMPAIGN_ID, CONTROLLED_EFFORT, CONTROLLED_MODEL,
    CONTROLLED_NETWORK_ENFORCEMENT, CONTROLLED_NETWORK_MODE, CONTROLLED_TASK_NETWORK_ENFORCEMENT,
    CONTROLLED_TRANSPORT_NETWORK_MODE, HARBOR_VERSION, HARNESSES, NETWORK_POLICY,
    NATIVE_NETWORK_ENFORCEMENT, NATIVE_NETWORK_MODE, NATIVE_TASK_NETWORK_ENFORCEMENT,
    NATIVE_TRANSPORT_NETWORK_MODE, Cell, Task, TaskRecord, bytes_digest, campaign_matrix,
    canonical, digest, fail, file_digest, harness_catalog_digest, load_tasks, model_roster_digest,
    qualification_harness_records, task_corpus_identity, task_identity, tree_digest, tree_files,
    verified_commit, write_json,
)

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
        receipts[task_id] = receipt
    task_digest = digest([
        task_identity(
            task,
            str(receipts[task.id]["fixture"]["tree_digest"]),
            file_digest(task.task_dir / "instruction.md"),
            file_digest(task.task_dir / "task.toml"),
            file_digest(task.task_dir / "grader.py"),
            file_digest(task.task_dir / "reference.patch"),
        )
        for task in tasks.values()
    ])
    pack_manifest = json.loads((PACKAGE / "compositions" / "digests.json").read_text(encoding="utf-8"))
    pack = {name: pack_manifest[name] for name in ("controlled_raw", "controlled_enriched")}
    return {
        "roster_digest": model_roster_digest(),
        "catalog_digest": harness_catalog_digest(),
        "harness_digest": harness_catalog_digest(),
        "adapter_digest": digest([entry["adapter"] for entry in qualification_harness_records()]),
        "pack_digest": digest(pack),
        "mcp_digest": digest({"identity": "none", "tools": [], "network": "denied"}),
        "task_digest": task_digest,
        "grader_digest": digest([receipts[task_id]["reference"]["grader_digest"] for task_id in tasks]),
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
    for key in ("roster_digest", "catalog_digest", "harness_digest", "adapter_digest", "pack_digest", "mcp_digest", "task_digest", "grader_digest", "profile_digest"):
        if not _valid_digest(stage.get(key)):
            fail(f"{stage_id} stage manifest digest is invalid: {key}")
    for key in ("crucible_binary_digest", "prime_package_digest"):
        if stage.get(key) is not None and not _valid_digest(stage.get(key)):
            fail(f"{stage_id} stage manifest digest is invalid: {key}")
    for key in ("dockerfile_digests", "package_digests"):
        values = stage.get(key)
        if not isinstance(values, list) or any(not _valid_digest(value) for value in values):
            fail(f"{stage_id} stage manifest digest list is invalid: {key}")
    probe = stage.get("controlled_tool_surface_probe")
    if probe is not None and (not isinstance(probe, dict) or probe.get("status") != "passed" or probe.get("task_network") != "denied_by_tool_and_sandbox" or not isinstance(probe.get("adapters"), list) or len(probe["adapters"]) < 3):
        fail(f"{stage_id} controlled tool surface probe is invalid")
    for field, policy_key in {
        "transport_network_mode": "transport_network_mode",
        "network_enforcement": "network_enforcement",
        "task_network_enforcement": "task_network_enforcement",
    }.items():
        expected = {name: NETWORK_POLICY[name][policy_key] for name in ("controlled", "native_default")}
        if stage.get(field) != expected:
            fail(f"{stage_id} stage manifest network contract is stale: {field}")
        schema_network = properties[field].get("properties", {})
        if {name: schema_network[name].get("const") for name in expected} != expected:
            fail(f"stage manifest schema network contract is stale: {field}")
    if stage.get("retry_policy") != {"product_retry": 0, "transport_retry": 0}:
        fail(f"{stage_id} stage manifest retry policy is invalid")
    decision = stage.get("decision_policy")
    if not isinstance(decision, dict) or decision.get("hard_pass_requires_all_tasks") is not True or decision.get("native_default_separate") is not True:
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
    manifest = json.loads((PACKAGE / "compositions" / "digests.json").read_text(encoding="utf-8"))
    assets: dict[str, str] = {}
    digests: dict[str, str] = {}
    for name in ("controlled_raw", "controlled_enriched"):
        path = PACKAGE / "compositions" / manifest[name]["path"]
        actual = file_digest(path)
        if actual != manifest[name]["sha256"]:
            fail(f"composition digest mismatch: {name}")
        assets[name], digests[name] = path.read_text(encoding="utf-8"), actual
    if any(not value.strip() for value in assets.values()):
        fail("controlled composition assets must not be empty")
    return assets, digests


def validate_smoke() -> dict[str, str]:
    path = PACKAGE / "smoke" / "harness-census-v0.json"
    smoke = json.loads(path.read_text(encoding="utf-8"))
    cells = smoke.get("smoke_cells", [])
    expected = [{**row, "task_ids": list(load_tasks())} for row in campaign_matrix()]
    if cells != expected:
        fail("smoke cells do not match the canonical nine-cell matrix")
    if "blocked_sentinels" in smoke or any("row_id" in cell or "provider_route_resolved" in cell for cell in cells):
        fail("smoke artifact contains synthetic availability claims")
    stage_path = PACKAGE / "smoke" / "stage-manifest.json"
    validate_stage_manifest(json.loads(stage_path.read_text(encoding="utf-8")), stage_id="smoke")
    return {"smoke_digest": bytes_digest(path.read_bytes())}


def task_prompt(task: Task, composition: str, assets: Mapping[str, str]) -> str:
    prompt = (task.task_dir / "instruction.md").read_text(encoding="utf-8").strip()
    if composition == "native_default":
        return prompt + "\n"
    value = prompt + "\n\n" + assets["controlled_raw"].strip()
    if composition == "controlled_enriched":
        value += "\n\n" + assets["controlled_enriched"].strip()
    return value + "\n"


def staged_task_toml(task: Task, composition: str) -> tuple[str, str]:
    import tomllib
    text = (task.task_dir / "task.toml").read_text(encoding="utf-8")
    expected = NATIVE_NETWORK_MODE if composition == "native_default" else CONTROLLED_NETWORK_MODE
    marker = f'network_mode = "{NATIVE_NETWORK_MODE}"'
    if marker not in text:
        fail(f"task manifest has no baseline network mode: {task.id}")
    staged = text if composition == "native_default" else text.replace(marker, f'network_mode = "{CONTROLLED_NETWORK_MODE}"', 1)
    if tomllib.loads(staged).get("environment", {}).get("network_mode") != expected:
        fail(f"staged network mode is invalid: {task.id}")
    return staged, expected


def prime_package_info(path: Path) -> dict[str, str]:
    metadata_path = path / "package.json"
    if not path.is_dir() or not metadata_path.is_file():
        fail(f"Prime package directory is missing: {path}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("name") != "prime-agent" or metadata.get("version") != "0.7.0":
        fail("Prime package must be prime-agent version 0.7.0")
    binary = metadata.get("bin", {}).get("prime-agent")
    if binary != "dist/bundle/cli.js" or not (path / binary).is_file():
        fail("Prime package bin must point to dist/bundle/cli.js")
    runtime = path / "dist" / "prime-agent-runtime"
    if not (runtime / "pyproject.toml").is_file() or not (runtime / "src" / "rlm" / "__init__.py").is_file():
        fail("Prime package must include dist/prime-agent-runtime")
    return {"package": "prime-agent@0.7.0", "version": "0.7.0", "source_kind": "operator_supplied_package", "digest": tree_digest(path, exclude_git=False)}


def stage_prime_package(root: Path, source: Path) -> dict[str, str]:
    info = prime_package_info(source)
    destination = root / "packages" / f"prime-agent-{info['digest'][:16]}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, symlinks=True)
    if tree_digest(destination, exclude_git=False) != info["digest"]:
        fail("staged Prime package digest changed")
    return {**info, "path": str(destination)}

def runtime_package_info(harness: str) -> dict[str, str]:
    spec = HARNESSES[harness]
    path = PACKAGE / "packages" / harness
    metadata_path, lock_path = path / "package.json", path / "package-lock.json"
    if not metadata_path.is_file() or not lock_path.is_file():
        fail(f"locked runtime package is missing for {harness}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    expected = {spec.package.rsplit("@", 1)[0]: spec.version, "bun": BUN_VERSION}
    if metadata.get("private") is not True or metadata.get("dependencies") != expected:
        fail(f"locked runtime package dependencies are invalid for {harness}")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    root = lock.get("packages", {}).get("", {})
    if lock.get("lockfileVersion") != 3 or root.get("dependencies") != expected:
        fail(f"runtime package lock does not bind the declared dependencies for {harness}")
    unpinned = [
        name
        for name, value in lock.get("packages", {}).items()
        if name and isinstance(value, dict) and not value.get("link") and not value.get("integrity")
    ]
    if unpinned:
        fail(f"runtime package lock has entries without integrity for {harness}: {unpinned}")
    return {
        "package": spec.package,
        "version": spec.version,
        "source_kind": "checked_in_npm_lock",
        "digest": tree_digest(path, exclude_git=False),
        "path": str(path),
    }


def harness_package_info(harness: str, prime_package: dict[str, str] | None) -> dict[str, str]:
    if harness != "prime":
        return runtime_package_info(harness)
    if prime_package is None:
        fail("Prime package metadata is missing")
    return prime_package




def dockerfile(harness: str, package_name: str) -> str:
    spec = HARNESSES[harness]
    base = "FROM node:22.19.0-bookworm-slim\nWORKDIR /workspace\nRUN node --version | grep -Eq '^v(22\\.(19|[2-9][0-9])\\.|2[3-9]\\.)'\n"
    packages = "python3 ca-certificates unzip" + (" bwrap coreutils ipython3 python3-pip" if harness == "prime" else "")
    install = f"RUN apt-get update && apt-get install -y --no-install-recommends {packages} && rm -rf /var/lib/apt/lists/*\n"
    labels = f'LABEL org.misty-step.harness="{harness}"\nLABEL org.misty-step.agent-package="{spec.package}"\n'
    if harness == "prime":
        install += f"COPY {package_name}/ /opt/prime-agent/\nRUN python3 -m pip install --break-system-packages /opt/prime-agent/dist/prime-agent-runtime\nRUN python3 -c 'import ipykernel, rlm; assert callable(rlm.run)'\nRUN python3 -c 'import IPython'\nRUN node -e 'const p=require(\"/opt/prime-agent/package.json\"); if(p.name!==\"prime-agent\"||p.version!==\"0.7.0\"||p.bin?.[\"prime-agent\"]!==\"dist/bundle/cli.js\") process.exit(1)'\nRUN ln -sf /opt/prime-agent/dist/bundle/cli.js /usr/local/bin/prime-agent && ln -sf /usr/local/bin/prime-agent /usr/local/bin/prime\n"
        path = "/root/.bun/bin:${PATH}"
    else:
        binary = "omp" if harness == "omp" else "pi"
        install += f"COPY {package_name}/ /opt/harness/\nRUN cd /opt/harness && npm ci --omit=dev\nRUN /opt/harness/node_modules/.bin/bun --version | grep -Fx '{BUN_VERSION}'\nRUN ln -sf /opt/harness/node_modules/.bin/{binary} /usr/local/bin/{binary}\n"
        path = "/opt/harness/node_modules/.bin:${PATH}"
    return base + install + labels + f'ENV PATH="{path}"\nCOPY repo/ /workspace/\n'


def verifier_source(grader: Path, source_manifest: dict[str, str], allowed_paths: tuple[str, ...]) -> str:
    grader_encoded = base64.b64encode(grader.read_bytes()).decode("ascii")
    manifest_encoded = base64.b64encode(canonical({"files": source_manifest, "allowed_paths": list(allowed_paths)})).decode("ascii")
    return f'''#!/usr/bin/env python3
"""Campaign-mounted grader and hidden source-scope verifier."""
from __future__ import annotations
import base64
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
GRADER = base64.b64decode({grader_encoded!r})
MANIFEST = json.loads(base64.b64decode({manifest_encoded!r}))
LOG_DIR = Path(os.environ["HARNESS_CENSUS_LOG_DIR"])
def files(root):
    result = {{}}
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            value = b"SYMLINK:" + path.readlink().as_posix().encode()
        elif path.is_file():
            value = path.read_bytes()
        else:
            continue
        result[name] = hashlib.sha256(value).hexdigest()
    return result
def reward(payload, reward_value, status):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    report = {{"schema_version": "harness_census.grader_report.v1", "reward": reward_value, "status": status, "passed": reward_value == 1.0, "grader_report": payload}}
    (LOG_DIR / "reward.json").write_text(json.dumps(reward_value) + "\\n", encoding="utf-8")
    (LOG_DIR / "grader-report.json").write_text(json.dumps(report, sort_keys=True) + "\\n", encoding="utf-8")
def scope_check(workspace):
    before = MANIFEST["files"]
    after = files(workspace)
    added = sorted(set(after) - set(before))
    deleted = sorted(set(before) - set(after))
    changed = sorted(name for name in set(before) & set(after) if before[name] != after[name])
    outside = sorted(name for name in changed if name not in MANIFEST["allowed_paths"])
    root = workspace.resolve()
    unsafe = sorted(
        name
        for name in MANIFEST["allowed_paths"]
        if (workspace / name).is_symlink() or not (workspace / name).resolve().is_relative_to(root)
    )
    if added or deleted or outside or unsafe:
        reward({{"passed": False, "failed_check": "scope", "added_paths": added, "deleted_paths": deleted, "changed_outside_allowed_paths": outside, "unsafe_allowed_paths": unsafe}}, 0.0, "scope_failure")
        return False
    return True
def main():
    if len(sys.argv) != 2:
        reward({{"passed": False, "failed_check": "invalid-arguments"}}, 0.0, "quality_failure")
        raise SystemExit(2)
    workspace = Path(sys.argv[1])
    if not scope_check(workspace):
        raise SystemExit(1)
    namespace = {{"__name__": "embedded_grader"}}
    exec(compile(GRADER, "embedded-grader.py", "exec"), namespace)
    output = io.StringIO()
    code = 1
    with contextlib.redirect_stdout(output):
        try:
            sys.argv = ["embedded-grader.py", str(workspace)]
            namespace["main"]()
            code = 0
        except SystemExit as error:
            code = int(error.code) if isinstance(error.code, int) else 1
        except Exception as error:
            print(json.dumps({{"passed": False, "failed_check": "grader-exception", "detail": f"{{type(error).__name__}}: {{error}}"}}))
    lines = [line for line in output.getvalue().splitlines() if line.strip()]
    try:
        report = json.loads(lines[-1]) if lines else {{"passed": False, "failed_check": "no-report"}}
    except json.JSONDecodeError:
        report = {{"passed": False, "failed_check": "invalid-report"}}
    passed = code == 0 and report.get("passed") is True
    reward(report, 1.0 if passed else 0.0, "success" if passed else "quality_failure")
    print(json.dumps(report, sort_keys=True))
    raise SystemExit(0 if passed else 1)
if __name__ == "__main__":
    main()
'''


def stage_task(cell_dir: Path, task: Task, harness: str, composition: str, assets: Mapping[str, str], source_root: Path, package: dict[str, str]) -> TaskRecord:
    task_dir = cell_dir / "tasks" / task.id
    env, source = task_dir / "environment", task_dir / "environment" / "repo"
    archive_git_tree(source_repo(source_root, task), task.source_sha, source)
    (task_dir / "instruction.md").write_text(task_prompt(task, composition, assets), encoding="utf-8")
    package_name = "prime-package" if harness == "prime" else "runtime-package"
    shutil.copytree(package["path"], env / package_name, symlinks=True, copy_function=lambda source, destination: Path(destination).hardlink_to(source))
    docker_text = dockerfile(harness, package_name)
    (env / "Dockerfile").write_text(docker_text, encoding="utf-8")
    task_toml, network_mode = staged_task_toml(task, composition)
    (task_dir / "task.toml").write_text(task_toml, encoding="utf-8")
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
    comparison_task_digest = task_corpus_identity(task, source_digest, grader_digest, file_digest(task.task_dir / "reference.patch"))
    task_digest = task_identity(task, source_digest, file_digest(task_dir / "instruction.md"), file_digest(task_dir / "task.toml"), grader_digest, file_digest(task.task_dir / "reference.patch"))
    return TaskRecord(task.id, task_digest, comparison_task_digest, source_digest, grader_digest, bytes_digest(docker_text.encode()), package["digest"] if harness == "prime" else None, f"tasks/{task.id}", task.allowed_paths, task.immutable_paths, network_mode)


def probe_harbor_task_validity(cells: tuple[Cell, ...]) -> dict[str, object]:
    task_paths = sorted({cell.cell_dir / record.task_dir for cell in cells for record in cell.task_records}, key=str)
    task_ids = {path.name for path in task_paths}
    controlled = [record for cell in cells if cell.cell_kind == "controlled" for record in cell.task_records]
    if not controlled or {record.network_mode for record in controlled} != {CONTROLLED_NETWORK_MODE}:
        fail("controlled staged tasks do not use configured task network mode")
    if task_ids != set(load_tasks()):
        fail(f"staged Harbor task set is invalid: {sorted(task_ids)}")
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
        result = subprocess.run(["uvx", "--from", f"harbor=={HARBOR_VERSION}", "python", "-c", check, *map(str, task_paths)], text=True, capture_output=True, check=False)
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


def row_identity(harness: str, composition: str, model: str, effort: str, task_digest: str, composition_digest: str) -> str:
    return digest({"campaign_id": CAMPAIGN_ID, "harness": harness, "composition": composition, "model_requested": model, "effort_requested": effort, "task_digest": task_digest, "composition_digest": composition_digest})


def cohort_identity(model: str, effort: str, task_digest: str) -> str:
    return digest({"campaign_id": CAMPAIGN_ID, "model_requested": model, "effort_requested": effort, "task_digest": task_digest})


def build_cells(root: Path, assets: Mapping[str, str], composition_digests: Mapping[str, str], source_root: Path, adapter_root: Path, prime_package: dict[str, str] | None) -> tuple[Cell, ...]:
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
        task_set = sorted(([record.task_id, record.comparison_task_digest] for record in records), key=lambda value: value[0])
        task_set_digest = digest(task_set)
        task_set_size = len(task_set)
        cell_run_id = f"{CAMPAIGN_ID}--{cell_id}"
        retry_policy_digest = digest({"product_retry": 0, "transport_retry": 0})
        corpus_digest = digest([
            task_corpus_identity(
                tasks[record.task_id],
                record.source_tree_digest,
                record.grader_digest,
                file_digest(tasks[record.task_id].task_dir / "reference.patch"),
            )
            for record in records
        ])
        controlled = composition != "native_default"
        network_mode = CONTROLLED_NETWORK_MODE if controlled else NATIVE_NETWORK_MODE
        network_enforcement = CONTROLLED_NETWORK_ENFORCEMENT if controlled else NATIVE_NETWORK_ENFORCEMENT
        transport_mode = CONTROLLED_TRANSPORT_NETWORK_MODE if controlled else NATIVE_TRANSPORT_NETWORK_MODE
        task_enforcement = CONTROLLED_TASK_NETWORK_ENFORCEMENT if controlled else NATIVE_TASK_NETWORK_ENFORCEMENT
        allowed_hosts = AGENT_ALLOWED_HOSTS if network_enforcement == NETWORK_POLICY["native_default"]["network_enforcement"] else ()
        model, effort = row["model_requested"], row["effort_requested"]
        kwargs: Mapping[str, object] = {"composition": composition, "thinking": CONTROLLED_EFFORT} if controlled else {"composition": "native_default"}
        agent_kwargs_base_digest = digest({key: value for key, value in kwargs.items() if key not in {"composition", "thinking", "reasoning_effort"}})
        config: dict[str, object] = {"agent": harness, "agent_import_path": spec.adapter, "job_timeout_ms": 900000, "agent_kwargs": dict(kwargs)}
        if controlled:
            config["model"] = CONTROLLED_MODEL
        if allowed_hosts:
            config["agent_allowed_hosts"] = list(allowed_hosts)
        spec_json = {"schema_version": "crucible.eval_spec.v1", "id": cell_id, "task": CAMPAIGN_ID, "inputs": "Three history-free pinned repository repair tasks with deterministic graders.", "outputs": "Harbor verifier reward per task.", "graders": {"graders": [{"id": "harness_census_deterministic", "kind": "deterministic"}]}, "aggregation": "proportion", "uncertainty": {"method": "wilson", "confidence": 0.95}, "decision": "Native defaults remain separate from controlled comparisons.", "runner": {"kind": "harbor_task", "corpus": {"source": "harbor_tasks", "config": config, "tasks": [{"task_id": record.task_id, "task_dir": record.task_dir} for record in records]}}}
        spec_path = cell_dir / "eval.json"
        write_json(spec_path, spec_json)
        composition_digest = composition_digests.get(composition, digest({"composition": "native_default"}))
        docker_digests = tuple(sorted({record.dockerfile_digest for record in records}))
        package_digest = package["digest"]
        prime_digest = package["digest"] if harness == "prime" else None
        row_id = row_identity(
            harness,
            composition,
            CONTROLLED_MODEL,
            CONTROLLED_EFFORT,
            task_digest,
            composition_digest,
        ) if controlled else None
        cohort_id = cohort_identity(CONTROLLED_MODEL, CONTROLLED_EFFORT, corpus_digest) if controlled else None
        baseline_id = digest({"campaign_id": CAMPAIGN_ID, "harness": harness, "version": spec.version, "composition": composition, "task_digest": task_digest}) if not controlled else None
        profile = digest({"harness": harness, "version": spec.version, "adapter_digest": adapter_digest, "kwargs": kwargs, "task_digest": task_digest, "composition_digest": composition_digest, "package_digest": package_digest, "prime_package_digest": prime_digest, "dockerfile_digests": list(docker_digests), "transport_network_mode": transport_mode, "network_enforcement": network_enforcement, "task_network_enforcement": task_enforcement})
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
                prime_package_digest=prime_digest,
                dockerfile_digests=docker_digests,
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
            expected = {"agent": cell.harness, "agent_import_path": spec.adapter, "job_timeout_ms": 900000, "agent_kwargs": {"composition": "native_default"}, "agent_allowed_hosts": list(AGENT_ALLOWED_HOSTS)}
            valid = config == expected and cell.network_mode == NATIVE_NETWORK_MODE and cell.transport_network_mode == NATIVE_TRANSPORT_NETWORK_MODE and cell.network_enforcement == NATIVE_NETWORK_ENFORCEMENT and cell.task_network_enforcement == NATIVE_TASK_NETWORK_ENFORCEMENT and cell.agent_allowed_hosts == AGENT_ALLOWED_HOSTS and cell.model_requested is None and cell.effort_requested is None and cell.provider_route_resolved is None and cell.provider_effort_resolved is None and cell.default_resolution_source is None
        else:
            expected = {"agent": cell.harness, "agent_import_path": spec.adapter, "job_timeout_ms": 900000, "model": CONTROLLED_MODEL, "agent_kwargs": {"composition": cell.composition, "thinking": CONTROLLED_EFFORT}, "agent_allowed_hosts": list(AGENT_ALLOWED_HOSTS)}
            valid = config == expected and cell.network_mode == CONTROLLED_NETWORK_MODE and cell.transport_network_mode == CONTROLLED_TRANSPORT_NETWORK_MODE and cell.network_enforcement == CONTROLLED_NETWORK_ENFORCEMENT and cell.task_network_enforcement == CONTROLLED_TASK_NETWORK_ENFORCEMENT and cell.agent_allowed_hosts == AGENT_ALLOWED_HOSTS and cell.model_requested == CONTROLLED_MODEL and cell.effort_requested == CONTROLLED_EFFORT and cell.provider_route_resolved == CONTROLLED_MODEL and cell.provider_effort_resolved == CONTROLLED_EFFORT
        if not valid:
            fail(f"staged config or metadata shape is invalid: {cell.cell_id}")
    return tuple(cells)


def write_harbor_wrapper(root: Path) -> Path:
    wrapper = root / "bin" / "harbor"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text(f"#!/bin/sh\nset -eu\nexec uvx --from harbor=={HARBOR_VERSION} harbor \"$@\"\n", encoding="utf-8")
    wrapper.chmod(0o755)
    return wrapper


def read_verifier_result(log_dir: Path) -> tuple[float, dict[str, object]]:
    reward_path, report_path = log_dir / "reward.json", log_dir / "grader-report.json"
    if not reward_path.is_file() or not report_path.is_file():
        fail(f"staged verifier evidence is incomplete: {log_dir}")
    reward = json.loads(reward_path.read_text(encoding="utf-8"))
    if isinstance(reward, bool) or not isinstance(reward, (int, float)):
        fail(f"Harbor reward.json must contain one numeric value: {reward!r}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        fail(f"grader report is not an object: {report!r}")
    return float(reward), report


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
