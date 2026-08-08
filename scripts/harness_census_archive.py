"""Safe extraction of pinned Git archives into a workspace."""
from __future__ import annotations

import io
from pathlib import Path
import re
import subprocess
import tarfile

SHA40 = re.compile(r"^[0-9a-f]{40}$")

def archive_git_tree(repo: Path, commit: str, destination: Path) -> None:
    if not SHA40.fullmatch(commit):
        raise RuntimeError(f"archive commit must be a full lowercase 40-hex SHA: {commit}")
    if not repo.is_dir():
        raise RuntimeError(f"pinned repository is missing: {repo}")
    result = subprocess.run(
        ["git", "-C", str(repo), "archive", commit],
        check=False,
        capture_output=True,
    )
    if result.returncode:
        detail = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"cannot export {repo} at {commit}: {detail}")
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:") as archive:
        root = destination.resolve()
        for member in archive.getmembers():
            target = (destination / member.name).resolve()
            if target != root and root not in target.parents:
                raise RuntimeError(f"archive path escapes workspace: {member.name}")
            if member.issym() or member.islnk():
                link_target = (target.parent / member.linkname).resolve()
                if link_target != root and root not in link_target.parents:
                    raise RuntimeError(f"archive link escapes workspace: {member.name}")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(member.linkname)
            elif member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise RuntimeError(f"cannot read archive member: {member.name}")
                target.write_bytes(source.read())
                target.chmod(member.mode & 0o777)
