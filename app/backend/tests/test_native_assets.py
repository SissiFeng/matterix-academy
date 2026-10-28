"""Offline asset-integrity and HTTPS transport checks; no GPU/browser evidence."""

import hashlib
import io
import sys
from types import ModuleType, SimpleNamespace

import pytest
from academy import native_assets


@pytest.fixture
def assets(monkeypatch, tmp_path):
    root = tmp_path.resolve() / "nvidia-ground"
    payload = b"pinned ground fixture"
    monkeypatch.setattr(
        native_assets, "FILES", {"default_environment.usd": hashlib.sha256(payload).hexdigest()}
    )
    requests = []

    def open_asset(url, timeout):
        requests.append((url, timeout))
        return io.BytesIO(payload)

    monkeypatch.setattr(
        native_assets.urllib.request, "build_opener", lambda *_: SimpleNamespace(open=open_asset)
    )
    return root, payload, requests


def test_explicit_preparation_downloads_once_and_runtime_never_downloads(assets):
    root, payload, requests = assets
    with pytest.raises(RuntimeError, match="missing"):
        native_assets.verified_ground(root)
    assert requests == []
    assert native_assets.prepare(root) == str(root / "default_environment.usd")
    assert (root / "default_environment.usd").read_bytes() == payload
    assert requests == [(native_assets.ROOT_URL + "default_environment.usd", 20)]
    native_assets.prepare(root)
    native_assets.verified_ground(root)
    assert len(requests) == 1
    (root / "default_environment.usd").write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="changed"):
        native_assets.verified_ground(root)


def test_changed_download_never_replaces_existing_file(assets, monkeypatch):
    root, _, _ = assets
    root.mkdir()
    target = root / "default_environment.usd"
    target.write_bytes(b"retain invalid file for diagnosis")
    monkeypatch.setattr(
        native_assets.urllib.request,
        "build_opener",
        lambda *_: SimpleNamespace(open=lambda *_a, **_k: io.BytesIO(b"wrong")),
    )
    with pytest.raises(RuntimeError, match="SHA256"):
        native_assets.prepare(root)
    assert target.read_bytes() == b"retain invalid file for diagnosis"
    assert list(root.iterdir()) == [target]


def test_redirects_and_symlink_cache_fail_closed(assets, tmp_path):
    root, _, _ = assets
    with pytest.raises(ValueError, match="redirect"):
        native_assets.NoRedirect().redirect_request(None, None, 302, "", {}, "http://example.com")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    root.symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        native_assets.prepare(root)
    assert list(elsewhere.iterdir()) == []


def test_native_binding_changes_only_asset_location(assets, monkeypatch):
    root, _, _ = assets
    native_assets.prepare(root)
    original = type(
        "GroundPlaneCfg",
        (),
        {
            "usd_path": native_assets.ROOT_URL + "default_environment.usd",
            "__init__": lambda self, **kw: self.__dict__.update(kw),
        },
    )
    env = SimpleNamespace(GroundPlaneCfg=original)
    for name in (
        "isaaclab",
        "isaaclab.sim",
        "isaaclab.sim.spawners",
        "isaaclab.sim.spawners.from_files",
        "matterix",
        "matterix.envs",
    ):
        module = ModuleType(name)
        module.__path__ = []
        monkeypatch.setitem(sys.modules, name, module)
    config = ModuleType("isaaclab.sim.spawners.from_files.from_files_cfg")
    config.GroundPlaneCfg = original
    monkeypatch.setitem(sys.modules, config.__name__, config)
    sys.modules["matterix.envs"].matterix_base_env = env
    native_assets.configure_ground(root)
    instance = env.GroundPlaneCfg(color=(0.005, 0.015, 0.08))
    assert instance.usd_path == str(root / "default_environment.usd")
    assert instance.color == (0.005, 0.015, 0.08)
    assert original.usd_path == native_assets.ROOT_URL + "default_environment.usd"
