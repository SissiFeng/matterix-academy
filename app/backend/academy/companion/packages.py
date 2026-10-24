"""Checksum-verified, bounded tar/ZIP staging. Staging never executes installers."""

import hashlib
import os
import re
import shutil
import stat
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from .config import private_directory


def _member_path(name: str, seen: set[str]) -> PurePosixPath:
    path = PurePosixPath(name)
    normalized = str(path)
    if (
        path.is_absolute()
        or not path.parts
        or ".." in path.parts
        or "\\" in name
        or "\x00" in name
        or ":" in name
        or normalized != name.rstrip("/")
        or normalized in seen
        or len(name) > 512
    ):
        raise ValueError("Unsafe archive member path or duplicate")
    seen.add(normalized)
    return path


def _copy_member(source, target: Path, declared_size: int):
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with source, os.fdopen(fd, "wb") as output:
        remaining = declared_size
        while remaining:
            chunk = source.read(min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError("Truncated artifact member")
            remaining -= len(chunk)
            output.write(chunk)
        if source.read(1):
            raise ValueError("Artifact member exceeds declared size")
        output.flush()
        os.fsync(output.fileno())


def _extract_zip(snapshot, staging, max_bytes, max_files, max_ratio):
    with zipfile.ZipFile(snapshot) as archive:
        members = archive.infolist()
        if len(members) > max_files:
            raise ValueError("Artifact file limit exceeded")
        seen, expanded, checked = set(), 0, []
        for member in members:
            path = _member_path(member.orig_filename, seen)
            mode = member.external_attr >> 16
            file_type = stat.S_IFMT(mode)
            if (
                member.orig_filename != member.filename
                or member.flag_bits & 1
                or member.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                or file_type not in {0, stat.S_IFREG, stat.S_IFDIR}
                or mode & 0o7000
                or member.is_dir()
                and (member.file_size or file_type == stat.S_IFREG)
                or not member.is_dir()
                and file_type == stat.S_IFDIR
            ):
                raise ValueError("Unsafe ZIP member type, mode or encryption")
            expanded += member.file_size
            if (
                expanded > max_bytes
                or member.file_size < 0
                or member.compress_size < 0
                or member.file_size > max(1, member.compress_size) * max_ratio
            ):
                raise ValueError("Artifact expanded/compression limit exceeded")
            checked.append((member, path))
        for member, path in checked:
            target = staging.joinpath(*path.parts)
            if member.is_dir():
                target.mkdir(mode=0o700, parents=True, exist_ok=True)
            else:
                _copy_member(archive.open(member), target, member.file_size)


def _extract_tar(snapshot, staging, max_bytes, max_files):
    with tarfile.open(fileobj=snapshot, mode="r:*") as archive:
        members, seen, expanded = [], set(), 0
        for member in archive:
            path = _member_path(member.name, seen)
            if (
                len(members) >= max_files
                or not (member.isfile() or member.isdir())
                or member.mode & 0o7000
                or member.size < 0
            ):
                raise ValueError("Unsafe archive member")
            expanded += member.size
            if expanded > max_bytes:
                raise ValueError("Artifact expanded limits exceeded")
            members.append((member, path))
        for member, path in members:
            target = staging.joinpath(*path.parts)
            if member.isdir():
                target.mkdir(mode=0o700, parents=True, exist_ok=True)
            else:
                source = archive.extractfile(member)
                if source is None:
                    raise ValueError("Missing artifact data")
                _copy_member(source, target, member.size)


def stage_archive(
    archive: Path,
    expected_sha256: str,
    destination: Path,
    *,
    max_bytes: int = 512 * 1024 * 1024,
    max_files: int = 10000,
    max_compression_ratio: int = 200,
) -> Path:
    if not re.fullmatch(r"[a-f0-9]{64}", expected_sha256):
        raise ValueError("Expected artifact checksum is required")
    if max_bytes < 1 or max_files < 0 or max_compression_ratio < 1:
        raise ValueError("Invalid archive limits")
    parent = private_directory(destination.parent)
    if destination.exists() or destination.is_symlink():
        raise ValueError("Refusing to replace an existing installation/staging directory")
    staging = Path(tempfile.mkdtemp(prefix=".verified-stage-", dir=parent))
    try:
        # Hash a private snapshot, never reopen a mutable caller download after verification.
        with tempfile.TemporaryFile(dir=parent) as snapshot:
            fd = os.open(archive, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as source:
                info = os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes:
                    raise ValueError("Invalid or oversized artifact")
                hasher, copied = hashlib.sha256(), 0
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    copied += len(chunk)
                    if copied > max_bytes:
                        raise ValueError("Artifact compressed limit exceeded")
                    hasher.update(chunk)
                    snapshot.write(chunk)
                if hasher.hexdigest() != expected_sha256:
                    raise ValueError("Artifact SHA256 mismatch")
            snapshot.seek(0)
            if zipfile.is_zipfile(snapshot):
                snapshot.seek(0)
                _extract_zip(snapshot, staging, max_bytes, max_files, max_compression_ratio)
            else:
                snapshot.seek(0)
                _extract_tar(snapshot, staging, max_bytes, max_files)
        staging.rename(destination)
        return destination
    except BaseException:
        shutil.rmtree(staging)
        raise
