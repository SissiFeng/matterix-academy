"""Offline archive resource-boundary regressions; no installer or robot activity."""

import hashlib
import io
import struct
import tarfile
import zipfile

import pytest
from academy.companion import packages


def make_archive(tmp_path, kind, names):
    path = tmp_path / ("artifact." + kind)
    if kind == "zip":
        with zipfile.ZipFile(path, "w") as archive:
            for name in names:
                archive.writestr(name, b"" if name.endswith("/") else b"fixture")
    else:
        with tarfile.open(path, "w") as archive:
            for name in names:
                entry = tarfile.TarInfo(name)
                if name.endswith("/"):
                    entry.type = tarfile.DIRTYPE
                    archive.addfile(entry)
                else:
                    entry.size = len(b"fixture")
                    archive.addfile(entry, io.BytesIO(b"fixture"))
    return path


def stage(path, tmp_path, **limits):
    return packages.stage_archive(
        path,
        hashlib.sha256(path.read_bytes()).hexdigest(),
        tmp_path / "private" / "release",
        **limits,
    )


def forbid_eager_zip(*args, **kwargs):
    raise AssertionError("Unbounded ZIP metadata reached the eager parser")


@pytest.mark.parametrize("underreported", [False, True])
def test_zip_entry_limit_precedes_eager_parse_even_with_forged_count(
    tmp_path, monkeypatch, underreported
):
    path = make_archive(tmp_path, "zip", ["one", "two", "three"])
    if underreported:
        data = bytearray(path.read_bytes())
        end = data.rfind(b"PK\x05\x06")
        struct.pack_into("<HH", data, end + 8, 1, 1)
        path.write_bytes(data)
    monkeypatch.setattr(packages.zipfile, "ZipFile", forbid_eager_zip)
    with pytest.raises(ValueError, match="file limit"):
        stage(path, tmp_path, max_files=2)
    assert list((tmp_path / "private").iterdir()) == []


def test_zip_metadata_bytes_are_bounded_before_eager_parse(tmp_path, monkeypatch):
    path = make_archive(tmp_path, "zip", ["one", "two"])
    monkeypatch.setattr(packages, "MAX_ZIP_DIRECTORY_BYTES", 50)
    monkeypatch.setattr(packages.zipfile, "ZipFile", forbid_eager_zip)
    with pytest.raises(ValueError, match="metadata limit"):
        stage(path, tmp_path)
    assert list((tmp_path / "private").iterdir()) == []


def test_zip_count_mismatch_is_rejected_before_eager_parse(tmp_path, monkeypatch):
    path = make_archive(tmp_path, "zip", ["one", "two"])
    data = bytearray(path.read_bytes())
    end = data.rfind(b"PK\x05\x06")
    struct.pack_into("<HH", data, end + 8, 1, 1)
    path.write_bytes(data)
    monkeypatch.setattr(packages.zipfile, "ZipFile", forbid_eager_zip)
    with pytest.raises(ValueError, match="count mismatch"):
        stage(path, tmp_path)


def test_zip64_directory_is_rejected_before_eager_parse(tmp_path, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(zipfile, "ZIP_FILECOUNT_LIMIT", 1)
        path = make_archive(tmp_path, "zip", ["one", "two"])
    monkeypatch.setattr(packages.zipfile, "ZipFile", forbid_eager_zip)
    with pytest.raises(ValueError, match="ZIP64"):
        stage(path, tmp_path)


def test_regular_directory_with_zip64_local_header_remains_supported(tmp_path):
    path = tmp_path / "local-zip64.zip"
    with zipfile.ZipFile(path, "w") as archive:
        with archive.open("fixture", "w", force_zip64=True) as output:
            output.write(b"fixture")
    assert (stage(path, tmp_path) / "fixture").read_bytes() == b"fixture"


@pytest.mark.parametrize("kind", ["zip", "tar"])
def test_implicit_directories_share_the_file_budget(tmp_path, monkeypatch, kind):
    path = make_archive(tmp_path, kind, ["a/b/one", "c/d/two"])

    def forbid_copy(*args, **kwargs):
        raise AssertionError("Archive nodes must be bounded before extraction")

    monkeypatch.setattr(packages, "_copy_member", forbid_copy)
    with pytest.raises(ValueError, match="including parent directories"):
        stage(path, tmp_path, max_files=5)
    assert list((tmp_path / "private").iterdir()) == []


@pytest.mark.parametrize("kind", ["zip", "tar"])
def test_shared_and_explicit_directories_are_counted_once(tmp_path, kind):
    path = make_archive(tmp_path, kind, ["shared/", "shared/a", "shared/b", "other/x"])
    directory = stage(path, tmp_path, max_files=5)
    assert len(list(directory.rglob("*"))) == 5
    assert (directory / "other/x").read_bytes() == b"fixture"


def test_tar_gzip_pax_bomb_is_bounded_before_tarfile_parses_extensions(tmp_path, monkeypatch):
    path = tmp_path / "pax-bomb.tar.gz"
    with tarfile.open(path, "w:gz", pax_headers={"comment": "x" * 1_000_000}) as archive:
        entry = tarfile.TarInfo("payload")
        entry.size = 1
        archive.addfile(entry, io.BytesIO(b"x"))
    assert path.stat().st_size < 4096

    def forbid_parser(*args, **kwargs):
        raise AssertionError("Decompression must be bounded before extension parsing")

    monkeypatch.setattr(packages.tarfile, "open", forbid_parser)
    with pytest.raises(ValueError, match="TAR decompressed container limit"):
        stage(path, tmp_path, max_bytes=4096, max_files=1)
    assert list((tmp_path / "private").iterdir()) == []


@pytest.mark.parametrize("extension", [tarfile.XHDTYPE, tarfile.GNUTYPE_LONGNAME])
def test_tar_declared_extension_size_is_checked_before_allocation(tmp_path, extension):
    path = tmp_path / "oversized-extension.tar"
    entry = tarfile.TarInfo("metadata")
    entry.type, entry.size = extension, 1_000_000_000_000
    path.write_bytes(entry.tobuf(format=tarfile.GNU_FORMAT) + b"\0" * 1024)
    with pytest.raises(ValueError, match="TAR metadata limit"):
        stage(path, tmp_path, max_bytes=4096, max_files=1)
    assert list((tmp_path / "private").iterdir()) == []


def test_tar_extension_budget_is_cumulative(tmp_path, monkeypatch):
    path = tmp_path / "repeated-pax.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        for name in ("one", "two", "three"):
            entry = tarfile.TarInfo(name)
            entry.size = 1
            entry.pax_headers = {"comment": "x" * 4500}
            archive.addfile(entry, io.BytesIO(b"x"))
    monkeypatch.setattr(packages, "MAX_TAR_METADATA_BYTES", 512)
    with pytest.raises(ValueError, match="TAR metadata limit"):
        stage(path, tmp_path, max_bytes=65536, max_files=3)
    assert list((tmp_path / "private").iterdir()) == []


@pytest.mark.parametrize("compression", ["", "gz", "bz2", "xz"])
@pytest.mark.parametrize("archive_format", [tarfile.PAX_FORMAT, tarfile.GNU_FORMAT])
def test_ordinary_tar_compression_and_long_paths_remain_supported(
    tmp_path, compression, archive_format
):
    path = tmp_path / "ordinary.tar"
    name = "package/" + "a" * 180
    with tarfile.open(path, "w:" + compression, format=archive_format) as archive:
        entry = tarfile.TarInfo(name)
        entry.size = len(b"fixture")
        if archive_format == tarfile.PAX_FORMAT:
            entry.pax_headers = {"comment": "ordinary build metadata"}
        archive.addfile(entry, io.BytesIO(b"fixture"))
    directory = stage(path, tmp_path, max_bytes=16384, max_files=2)
    assert (directory / name).read_bytes() == b"fixture"
