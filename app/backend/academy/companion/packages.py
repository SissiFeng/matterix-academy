"""Checksum-verified, bounded tar/ZIP staging. Staging never executes installers."""

import hashlib
import os
import re
import shutil
import stat
import struct
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from .config import private_directory

MAX_ZIP_DIRECTORY_BYTES = 16 * 1024 * 1024


def _check_zip_directory(snapshot, max_files):
    """Bound metadata before ZipFile eagerly reads and allocates its directory."""
    snapshot.seek(0, os.SEEK_END)
    size = snapshot.tell()
    snapshot.seek(max(0, size - 65557))  # Fixed EOCD plus the maximum ZIP comment.
    tail = snapshot.read(65557)
    index = tail.rfind(b"PK\x05\x06")
    if index < 0 or len(tail) - index < 22:
        raise ValueError("Invalid ZIP directory")
    _, disk, start_disk, disk_count, count, length, offset, comment = struct.unpack_from(
        "<4s4H2LH", tail, index
    )
    end = size - len(tail) + index
    snapshot.seek(max(0, end - 20))
    locator = snapshot.read(4) if end >= 20 else b""
    if len(tail) - index != 22 + comment:
        raise ValueError("Invalid ZIP directory ending")
    if (
        disk
        or start_disk
        or disk_count != count
        or count == 0xFFFF
        or length == 0xFFFFFFFF
        or offset == 0xFFFFFFFF
        or locator == b"PK\x06\x07"
    ):
        # Neither format is needed within this installer's byte/entry limits.
        raise ValueError("Split and ZIP64 archive directories are unsupported")
    if count > max_files:
        raise ValueError("Artifact file limit exceeded")
    if length > MAX_ZIP_DIRECTORY_BYTES:
        raise ValueError("Artifact ZIP metadata limit exceeded")
    start = end - length
    if start < 0 or offset > start:
        raise ValueError("Invalid ZIP directory bounds")
    snapshot.seek(start)
    actual = 0
    while snapshot.tell() < end:
        header = snapshot.read(46)
        if len(header) != 46 or header[:4] != b"PK\x01\x02":
            raise ValueError("Invalid ZIP directory entry")
        actual += 1
        if actual > max_files:
            raise ValueError("Artifact file limit exceeded")
        name, extra, comment = struct.unpack_from("<HHH", header, 28)
        if (
            struct.unpack_from("<H", header, 34)[0]
            or snapshot.tell() + name + extra + comment > end
        ):
            raise ValueError("Invalid ZIP directory entry bounds")
        snapshot.seek(name + extra + comment, os.SEEK_CUR)
    if actual != count:
        raise ValueError("ZIP directory entry count mismatch")
    snapshot.seek(0)


def _count_nodes(path: PurePosixPath, nodes: set[tuple[str, ...]], max_files: int):
    # Account for implicit parent directories as well as explicit archive entries.
    for depth in range(1, len(path.parts) + 1):
        nodes.add(path.parts[:depth])
        if len(nodes) > max_files:
            raise ValueError("Artifact file limit exceeded (including parent directories)")


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
    _check_zip_directory(snapshot, max_files)
    with zipfile.ZipFile(snapshot) as archive:
        members = archive.infolist()
        if len(members) > max_files:
            raise ValueError("Artifact file limit exceeded")
        seen, nodes, expanded, checked = set(), set(), 0, []
        for member in members:
            path = _member_path(member.orig_filename, seen)
            _count_nodes(path, nodes, max_files)
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
        members, seen, nodes, expanded = [], set(), set(), 0
        for member in archive:
            path = _member_path(member.name, seen)
            _count_nodes(path, nodes, max_files)
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
