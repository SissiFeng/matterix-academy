"""Real private-cache filesystem checks with a synthetic launcher; no GPU evidence."""

import builtins
import json
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from academy import native_kit


@pytest.fixture
def cache(monkeypatch, tmp_path):
    path = tmp_path.resolve() / "worker-cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(path))
    return path


def test_private_cache_is_writable_without_modifying_installed_code(cache, tmp_path):
    code = tmp_path / "installed-code"
    code.mkdir(mode=0o555)
    mode = code.stat().st_mode
    root = native_kit.prepare_kit_root((code,))
    assert root == cache / "academy-kit"
    assert root.stat().st_uid == os.getuid()
    assert root.stat().st_mode & 0o777 == 0o700
    assert list(root.iterdir()) == []
    assert code.stat().st_mode == mode


def test_user_host_without_xdg_cache_uses_private_home_cache(monkeypatch, tmp_path):
    home = tmp_path.resolve() / "home"
    home.mkdir(mode=0o700)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setenv("HOME", str(home))
    root = native_kit.prepare_kit_root()
    assert root == home / ".cache/academy-kit"
    assert root.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("kind", ["relative", "space", "symlink", "installed", "shared"])
def test_unsafe_cache_fails_before_importing_isaac(monkeypatch, tmp_path, kind):
    base = tmp_path.resolve() / "cache"
    protected = ()
    if kind == "relative":
        base = Path("relative/cache")
    elif kind == "space":
        base = tmp_path.resolve() / "cache with spaces"
    elif kind == "symlink":
        target = tmp_path / "elsewhere"
        target.mkdir()
        base.symlink_to(target, target_is_directory=True)
    elif kind == "installed":
        protected = (base,)
    elif kind == "shared":
        base.mkdir(mode=0o777)
        base.chmod(0o777)
    monkeypatch.setenv("XDG_CACHE_HOME", str(base))
    imported = []
    original_import = builtins.__import__

    def observe(name, *args, **kwargs):
        if name.startswith("isaaclab"):
            imported.append(name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", observe)
    with pytest.raises(RuntimeError):
        native_kit.launch_native_app(headless=True, protected_roots=protected)
    assert imported == []


def test_existing_cache_symlink_is_rejected(cache, tmp_path):
    cache.mkdir()
    target = tmp_path / "outside"
    target.mkdir()
    (cache / "academy-kit").symlink_to(target, target_is_directory=True)
    with pytest.raises(RuntimeError, match="symlink"):
        native_kit.prepare_kit_root()
    assert list(target.iterdir()) == []


def test_readonly_cache_mount_is_rejected_before_import(cache, monkeypatch):
    def readonly(**_):
        raise PermissionError("read-only filesystem fixture")

    monkeypatch.setattr(native_kit.tempfile, "TemporaryFile", readonly)
    with pytest.raises(PermissionError, match="read-only"):
        native_kit.prepare_kit_root()


def test_cache_owned_by_another_user_is_rejected(cache, monkeypatch):
    owner = os.getuid()
    monkeypatch.setattr(native_kit.os, "getuid", lambda: owner + 1)
    with pytest.raises(RuntimeError, match="current worker"):
        native_kit.prepare_kit_root()


def fake_runtime(monkeypatch, root, *, token_escape=False):
    observed = []
    app = SimpleNamespace(closed=False)
    app.close = lambda: setattr(app, "closed", True)

    class Launcher:
        @staticmethod
        def add_app_launcher_args(parser):
            for name in ("device", "viz", "livestream", "kit_args"):
                parser.add_argument("--" + name)
            for name in ("headless", "enable_cameras"):
                parser.add_argument("--" + name, action="store_true")

        def __init__(self, args):
            assert root.is_dir() and root.stat().st_mode & 0o777 == 0o700
            # Match the exact pinned Lab implementation's whitespace splitting.
            assert args.kit_args.split() == ["--portable", "--portable-root", str(root)]
            observed.append(vars(args))
            self.app = app

    package = ModuleType("isaaclab")
    package.__path__ = []
    launcher = ModuleType("isaaclab.app")
    launcher.AppLauncher = Launcher
    carb = ModuleType("carb")
    carb.__path__ = []
    tokens = ModuleType("carb.tokens")
    tokens.get_tokens_interface = lambda: SimpleNamespace(
        resolve=lambda name: str(root.parent / "escape") if token_escape else str(root / name[2:-1])
    )
    carb.tokens = tokens
    for name, module in (
        ("isaaclab", package),
        ("isaaclab.app", launcher),
        ("carb", carb),
        ("carb.tokens", tokens),
    ):
        monkeypatch.setitem(sys.modules, name, module)
    return app, observed


@pytest.mark.parametrize("headless", [True, False])
def test_shared_launcher_preserves_render_flags_and_proves_private_kit_paths(
    cache, monkeypatch, capsys, headless
):
    root = cache / "academy-kit"
    app, observed = fake_runtime(monkeypatch, root)
    assert native_kit.launch_native_app(headless=headless) is app
    assert not app.closed
    args = observed[0]
    assert args["headless"] is headless
    assert args["enable_cameras"] is True
    assert args["device"] == "cuda:0" and args["viz"] == "kit" and args["livestream"] == "0"
    paths = json.loads(capsys.readouterr().out.split("ACADEMY_KIT_PATHS=", 1)[1])
    assert set(paths) == {"cache", "data", "logs", "omni_cache", "omni_data", "omni_logs"}
    for path in paths.values():
        assert Path(path).is_relative_to(root) and Path(path).is_dir()


def test_kit_token_escape_closes_app_and_cannot_create_outside_directory(cache, monkeypatch):
    root = cache / "academy-kit"
    app, _ = fake_runtime(monkeypatch, root, token_escape=True)
    with pytest.raises(RuntimeError, match="escaped"):
        native_kit.launch_native_app(headless=True)
    assert app.closed
    assert not (cache / "escape").exists()


def test_token_symlink_inside_cache_cannot_redirect_writes(cache, tmp_path):
    root = native_kit.prepare_kit_root()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)
    tokens = SimpleNamespace(resolve=lambda _: str(root / "escape" / "nested"))
    with pytest.raises(RuntimeError, match="escaped"):
        native_kit.verify_kit_paths(root, tokens)
    assert list(outside.iterdir()) == []
