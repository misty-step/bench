"""Build immutable OMP instruction context for the harness census."""
from __future__ import annotations

from dataclasses import dataclass
import json
import posixpath
from pathlib import Path
import subprocess
from typing import Iterable
from harness_census_common import MANIFEST, RAW_SKILL_DIGEST, bytes_digest, canonical
_CONTEXT = MANIFEST["context_pack"]
OMP_COMMIT = str(_CONTEXT["source_commit"])
OMP_REPOSITORY = str(_CONTEXT["source_repo"])
FORBIDDEN_SEGMENTS = frozenset(str(value) for value in _CONTEXT["forbidden_segments"])
FORBIDDEN_NAMES = frozenset(str(value) for value in _CONTEXT["forbidden_names"])
TASK_CONTEXT_NAMES = tuple(str(value) for value in _CONTEXT["task_context_names"])


@dataclass(frozen=True)
class ContextPack:
    manifest_digest: str
    pack_digest: str
    skill_digest: str
    skill_count: int
    context_bytes: bytes




def _git(source: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(source), *args], capture_output=True, check=False)
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"OMP source query failed: {detail}")
    return result.stdout

def _assert_pinned_source(source: Path) -> None:
    if not source.is_dir():
        raise RuntimeError(f"pinned OMP source is missing: {source}")
    observed = _git(source, "rev-parse", "--verify", f"{OMP_COMMIT}^{{commit}}").decode().strip()
    if observed != OMP_COMMIT:
        raise RuntimeError(f"OMP source does not contain pinned commit: {observed}")




def _tree(source: Path) -> dict[str, tuple[str, bytes]]:
    _assert_pinned_source(source)
    output = _git(source, "ls-tree", "-r", "-z", OMP_COMMIT, "--", "global")
    entries: dict[str, tuple[str, bytes]] = {}
    for item in output.decode("utf-8", errors="strict").split("\x00"):
        if not item:
            continue
        header, path = item.split("\t", 1)
        mode, _kind, _object_id = header.split(" ", 2)
        entries[path] = (mode, _git(source, "show", f"{OMP_COMMIT}:{path}"))
    return entries


def _safe_source_path(path: str) -> str:
    normalized = posixpath.normpath(path)
    if normalized.startswith("../") or normalized == ".." or not normalized.startswith("global/"):
        raise RuntimeError(f"OMP context path escapes global root: {path}")
    return normalized


def _resolved_skill_target(path: str, entries: dict[str, tuple[str, bytes]]) -> str:
    target = _safe_source_path(posixpath.join(posixpath.dirname(path), entries[path][1].decode("utf-8")))
    seen: set[str] = set()
    while target in entries and entries[target][0] == "120000":
        if target in seen:
            raise RuntimeError(f"OMP skill symlink cycle: {path}")
        seen.add(target)
        target = _safe_source_path(posixpath.join(posixpath.dirname(target), entries[target][1].decode("utf-8")))
    return target


def _global_entries(entries: dict[str, tuple[str, bytes]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    selected: dict[str, tuple[str, bytes, str]] = {}
    for path in ("global/AGENTS.md", "global/RULES.md"):
        if path not in entries or entries[path][0] != "100644":
            raise RuntimeError(f"required OMP context file is missing: {path}")
        selected[path] = (path, entries[path][1], "global_rule")
    for path, (mode, value) in entries.items():
        parts = path.split("/")
        if len(parts) == 4 and parts[:2] == ["global", "skills"] and parts[-1] == "SKILL.md":
            if mode != "100644":
                raise RuntimeError(f"skill entrypoint is not a regular file: {path}")
            selected[path] = (path, value, "skill_entrypoint")
        elif len(parts) == 3 and parts[:2] == ["global", "skills"] and mode == "120000":
            resolved = _resolved_skill_target(path, entries)
            entry = resolved if resolved.endswith("/SKILL.md") else f"{resolved}/SKILL.md"
            if entry not in entries or entries[entry][0] != "100644":
                raise RuntimeError(f"resolved skill entrypoint is missing: {path}")
            target = f"global/skills/{parts[2]}/SKILL.md"
            if target in selected:
                raise RuntimeError(f"OMP context has duplicate target path: {target}")
            selected[target] = (entry, entries[entry][1], "skill_entrypoint")
    if len({target for target in selected}) != len(selected):
        raise RuntimeError("OMP context has duplicate target paths")
    includes = [_record(source, target, kind, value, None) for target, (source, value, kind) in selected.items()]
    included_sources = {str(record["source_path"]) for record in includes}
    holdouts: list[dict[str, object]] = []
    for source, (mode, value) in entries.items():
        if mode not in {"100644", "100755", "120000"} or source in included_sources:
            continue
        parts = set(source.split("/"))
        if parts & FORBIDDEN_SEGMENTS or Path(source).name in FORBIDDEN_NAMES:
            kind = "forbidden_holdout"
        else:
            kind = "holdout"
        holdouts.append(_record(source, f"holdout/{source}", kind, value, None))
    return includes, holdouts


def _record(source: str, target: str, kind: str, value: bytes, task_id: str | None, source_repo: str = OMP_REPOSITORY, source_commit: str = OMP_COMMIT) -> dict[str, object]:
    return {
        "source_repo": source_repo,
        "source_commit": source_commit,
        "source_path": source,
        "target_path": target,
        "kind": kind,
        "task_id": task_id,
        "sha256": bytes_digest(value),
    }



def _framed(records: Iterable[dict[str, object]], values: dict[str, bytes]) -> bytes:
    output = bytearray()
    for record in records:
        target = str(record["target_path"])
        output.extend(f"\n===== {target} =====\n".encode("utf-8"))
        output.extend(values[record["sha256"]])
        if not output.endswith(b"\n"):
            output.extend(b"\n")
    return bytes(output).lstrip(b"\n")


def _global_pack(source: Path, forbidden_tokens: Iterable[bytes] = ()) -> tuple[dict[str, object], dict[str, bytes], bytes]:
    entries = _tree(source)
    includes, holdouts = _global_entries(entries)
    for record in includes:
        value = entries[str(record["source_path"])][1]
        if any(token and token in value for token in forbidden_tokens):
            raise RuntimeError(f"OMP context contains forbidden task material: {record['source_path']}")
    values = {record["sha256"]: entries[str(record["source_path"])][1] if str(record["source_path"]) in entries else b"" for record in includes}
    for record in includes:
        if not values[record["sha256"]]:
            source_path = str(record["source_path"])
            resolved = entries[source_path][1] if entries[source_path][0] != "120000" else b""
            if resolved:
                values[record["sha256"]] = resolved
            else:
                raise RuntimeError(f"context blob is missing: {source_path}")
    manifest: dict[str, object] = {
        "schema_version": "harness_census.context_manifest.v1",
        "source_repo": OMP_REPOSITORY,
        "source_commit": OMP_COMMIT,
        "includes": sorted(includes, key=lambda item: (str(item["task_id"]), str(item["target_path"]))),
        "holdouts": sorted(holdouts, key=lambda item: str(item["source_path"])),
    }
    skills = [record for record in includes if record["kind"] == "skill_entrypoint"]
    skill_bytes = _framed(sorted(skills, key=lambda item: str(item["target_path"])), values)
    return manifest, values, skill_bytes


def _task_context_records(task_id: str, source: Path, allowed_paths: tuple[str, ...], source_repository: str, commit: str) -> tuple[list[dict[str, object]], dict[str, bytes]]:
    root = source.resolve()
    records: dict[str, dict[str, object]] = {}
    values: dict[str, bytes] = {}
    for allowed in allowed_paths:
        candidate = source / allowed
        resolved_allowed = candidate.resolve()
        if root not in resolved_allowed.parents and resolved_allowed != root:
            raise RuntimeError(f"task allowed path escapes source root: {task_id}/{allowed}")
        parent = candidate.parent
        while True:
            for name in TASK_CONTEXT_NAMES:
                context_path = parent / name
                if not context_path.is_file():
                    continue
                resolved = context_path.resolve()
                if root not in resolved.parents and resolved != root:
                    raise RuntimeError(f"task context escapes source root: {task_id}/{context_path}")
                source_path = resolved.relative_to(root).as_posix()
                target_path = f"tasks/{task_id}/context/{source_path}"
                value = resolved.read_bytes()
                record = {
                    "source_repo": source_repository,
                    "source_commit": commit,
                    "source_path": source_path,
                    "target_path": target_path,
                    "kind": "task_context",
                    "task_id": task_id,
                    "sha256": bytes_digest(value),
                }
                records[target_path] = record
                values[record["sha256"]] = value
            if parent == root:
                break
            if root not in parent.parents:
                raise RuntimeError(f"task context parent escapes source root: {task_id}/{parent}")
            parent = parent.parent
    return sorted(records.values(), key=lambda item: str(item["target_path"])), values




def prepare_task_pack(root: Path, task_id: str, source: Path, source_repository: str, commit: str, allowed_paths: tuple[str, ...], omp_source: Path, forbidden_tokens: Iterable[bytes] = ()) -> ContextPack:
    global_manifest, global_values, global_skills = _global_pack(omp_source, forbidden_tokens)
    task_records, task_values = _task_context_records(task_id, source, allowed_paths, source_repository, commit)
    for record in task_records:
        value = task_values[record["sha256"]]
        if any(token and token in value for token in forbidden_tokens):
            raise RuntimeError(f"task context contains forbidden task material: {record['source_path']}")
    includes = list(global_manifest["includes"]) + task_records
    manifest = {**global_manifest, "includes": sorted(includes, key=lambda item: (str(item["task_id"]), str(item["target_path"]))) }
    manifest_digest = bytes_digest(canonical(manifest))
    values = {**global_values, **task_values}
    prompt_records = [dict(record, target_path=str(record["source_path"])) if record["task_id"] is not None else record for record in manifest["includes"]]
    context_bytes = _framed(prompt_records, values)
    pack_digest = bytes_digest(context_bytes)
    skill_digest = bytes_digest(global_skills)
    return ContextPack(manifest_digest, pack_digest, skill_digest, sum(1 for item in global_manifest["includes"] if item["kind"] == "skill_entrypoint"), context_bytes)


def raw_skill_digest() -> str:
    return RAW_SKILL_DIGEST
