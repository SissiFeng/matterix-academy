"""Exercise image supply-chain and lifetime guards without AWS or native execution."""

import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tarfile
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from academy import runtime_inventory as inventory
from academy.native_runner import NativeConfig

ROOT = Path(__file__).resolve().parents[3]


def script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "remaining,token,passes",
    [
        (7680, "session", True),
        (7679, "session", False),
        (None, "session", False),
        (None, None, True),
    ],
)
def test_frozen_credentials_cover_paid_timeout_and_cleanup(remaining, token, passes):
    module = script("ec2-gpu-build")
    now = datetime(2026, 10, 23, tzinfo=UTC)
    expires = now + timedelta(seconds=remaining) if remaining is not None else None
    if passes:
        module.credential_lifetime(expires, token, 7200, now)
    else:
        with pytest.raises(ValueError):
            module.credential_lifetime(expires, token, 7200, now)


class Download(io.BytesIO):
    headers = {}


@pytest.mark.parametrize("kind", ["content_length", "stream_size", "deadline", "digest"])
def test_driver_failure_is_bounded_and_preserves_previous_installer(tmp_path, monkeypatch, kind):
    module = script("ec2-gpu-driver")
    old = tmp_path / "nvidia-driver.run"
    old.write_bytes(b"previous verified artifact")
    response = Download(b"new payload exceeds fixture bound")
    if kind == "content_length":
        response.headers = {"Content-Length": "999"}
    monkeypatch.setattr(
        module, "MAX_INSTALLER_BYTES", 8 if kind in {"content_length", "stream_size"} else 100
    )
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *a, **kw: response)
    if kind == "deadline":
        ticks = iter([0, 0, 901])
        monkeypatch.setattr(module.time, "monotonic", lambda: next(ticks))
    with pytest.raises((ValueError, TimeoutError)):
        module.download({"url": "https://example.invalid/fixture", "sha256": "a" * 64}, tmp_path)
    assert old.read_bytes() == b"previous verified artifact"
    assert [f.name for f in tmp_path.iterdir()] == ["nvidia-driver.run"]


def test_driver_success_checks_digest_before_replacing(tmp_path, monkeypatch):
    module = script("ec2-gpu-driver")
    data = b"synthetic installer"
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *a, **kw: Download(data))
    driver = {"url": "https://example.invalid/fixture", "sha256": hashlib.sha256(data).hexdigest()}
    module.download(driver, tmp_path)
    assert (tmp_path / "nvidia-driver.run").read_bytes() == data
    assert json.loads((tmp_path / "driver.json").read_text()) == driver


def test_installed_lab_is_verified_by_pinned_wheel_bytes_not_version(tmp_path, monkeypatch):
    wheel = tmp_path / "isaaclab.whl"
    installed = tmp_path / "site"
    contents = {
        "isaaclab/__init__.py": b"VERSION='same-version'\n",
        "isaaclab-1.dist-info/METADATA": b"Version: same-version\n",
    }
    with zipfile.ZipFile(wheel, "w") as archive:
        for relative, body in contents.items():
            archive.writestr(relative, body)
            target = installed / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
        archive.writestr("isaaclab-1.dist-info/RECORD", b"installer rewrites this")
    monkeypatch.setitem(
        inventory.PROFILE, "isaaclab_wheel_sha256", hashlib.sha256(wheel.read_bytes()).hexdigest()
    )
    distribution = SimpleNamespace(locate_file=lambda relative: installed / relative)
    assert inventory.verify_installed_isaaclab(wheel, distribution)["verified"]
    (installed / "isaaclab/__init__.py").write_bytes(b"VERSION='same-version'\nINJECTED=True\n")
    assert not inventory.verify_installed_isaaclab(wheel, distribution)["verified"]
    monkeypatch.setitem(inventory.PROFILE, "isaaclab_wheel_sha256", "b" * 64)
    assert not inventory.verify_installed_isaaclab(wheel, distribution)["verified"]


def test_readonly_materialized_lfs_tree_needs_no_cache_and_detects_drift(tmp_path):
    module = script("ec2-gpu-sources")
    source = tmp_path / "repo"
    source.mkdir()

    def git(*args):
        return (
            subprocess.check_output(["git", "-C", str(source), *args], stderr=subprocess.DEVNULL)
            .decode()
            .strip()
        )

    git("init", "--quiet")
    git("config", "user.email", "fixture@example.invalid")
    git("config", "user.name", "Fixture")
    git("lfs", "install", "--local")
    git("lfs", "track", "*.usd")
    payload = b"materialized synthetic USD\n" * 100
    (source / "scene.usd").write_bytes(payload)
    git("add", ".")
    git("commit", "-qm", "Synthetic fixture")
    head = git("rev-parse", "HEAD")
    archive = tmp_path / "source.tar.gz"
    module.snapshot(source, head, archive)
    restored = tmp_path / "readonly"
    restored.mkdir()
    with tarfile.open(archive) as file:
        assert not any(name.startswith("./.git/lfs/") for name in file.getnames())
        file.extractall(restored, filter="data")
    try:
        for path in [restored, *restored.rglob("*")]:
            path.chmod(path.stat().st_mode & ~0o222)
        assert inventory.source_tree_clean(restored, head)
        assert not (restored / ".git/lfs").exists()
        NativeConfig(
            python=sys.executable,
            matterix_root=str(restored),
            assets_root=str(restored),
            assets_data_dir=str(restored),
            engine_version=head,
            asset_version=head,
            run_root=str(tmp_path / "runs"),
            frame_root=str(tmp_path / "frames"),
        ).verify()
        assert not (restored / ".git/lfs").exists()
        asset = restored / "scene.usd"
        asset.chmod(0o644)
        asset.write_bytes(payload.replace(b"synthetic", b"malicious"))
        asset.chmod(0o444)
        assert not inventory.source_tree_clean(restored, head)
    finally:
        for path in [restored, *restored.rglob("*")]:
            path.chmod(path.stat().st_mode | 0o200)


def test_paid_child_rechecks_same_frozen_expiration_after_slow_preflight(monkeypatch):
    module = script("ec2-gpu-build")
    started = datetime(2026, 10, 23, tzinfo=UTC)
    frozen = SimpleNamespace(access_key="key", secret_key="secret", token="session")
    provider = SimpleNamespace(
        _expiry_time=started + timedelta(seconds=7800), get_frozen_credentials=lambda: frozen
    )
    clock = [started]
    monkeypatch.setattr(module, "datetime", SimpleNamespace(now=lambda tz: clock[0]))
    session = SimpleNamespace(
        get_credentials=lambda: provider,
        client=lambda *a, **kw: SimpleNamespace(
            get_caller_identity=lambda: {"Account": "123456789012"}
        ),
    )
    env, captured_expiration = module.verified_environment(session, "123456789012", "ca-central-1")
    clock[0] += timedelta(seconds=121)
    # A separately refreshed provider must not make the already-frozen child token look fresh.
    provider._expiry_time = started + timedelta(hours=6)
    launches = []
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **kw: launches.append(a))
    with pytest.raises(ValueError, match="Refresh AWS credentials"):
        module.run_build(["packer", "build"], env, 7200, captured_expiration)
    assert launches == []
