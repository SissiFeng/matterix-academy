"""Real private-cache filesystem checks with a synthetic launcher; no GPU evidence."""

import argparse
import builtins
import json
import os
import subprocess
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
            class ExplicitHeadless(argparse.Action):
                def __call__(self, parser, namespace, values, option_string=None):
                    setattr(namespace, self.dest, True)
                    namespace.headless_explicit = True

            for name in ("device", "viz", "livestream", "kit_args"):
                parser.add_argument("--" + name)
            parser.set_defaults(headless=False, headless_explicit=False)
            parser.add_argument("--headless", action=ExplicitHeadless, nargs=0)
            parser.add_argument("--enable_cameras", action="store_true")

        def __init__(self, args, **config):
            assert root.is_dir() and root.stat().st_mode & 0o777 == 0o700
            # Match the exact pinned Lab implementation's whitespace splitting.
            assert args.kit_args.split() == ["--portable", "--portable-root", str(root)]
            # Pinned Lab's CLI headless handling disables visualizers even when
            # --viz kit is explicit; programmatic headless preserves rendering.
            if args.headless and args.headless_explicit and args.viz == "kit":
                raise RuntimeError("Explicit Kit visualizer was disabled by --headless")
            observed.append(vars(args))
            app.fast_shutdown = config.get("fast_shutdown", True)

            def close():
                app.closed = True
                if app.fast_shutdown:
                    raise SystemExit(0)

            app.close = close
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
    assert app.fast_shutdown is False
    args = observed[0]
    assert args["headless"] is headless
    assert args["headless_explicit"] is False
    assert args["enable_cameras"] is True
    assert args["device"] == "cuda:0" and args["viz"] == "kit" and args["livestream"] == "0"
    paths = json.loads(capsys.readouterr().out.split("ACADEMY_KIT_PATHS=", 1)[1])
    assert set(paths) == {"cache", "data", "logs", "omni_cache", "omni_data", "omni_logs"}
    for path in paths.values():
        assert Path(path).is_relative_to(root) and Path(path).is_dir()
    native_kit.close_native_app(app)
    assert app.closed  # The caller remains alive to save acceptance evidence.


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


def test_shutdown_preserves_active_failure_and_bounds_cleanup(cache, monkeypatch, capsys):
    app, _ = fake_runtime(monkeypatch, cache / "academy-kit")
    native_kit.launch_native_app(headless=True)
    watchdog = []
    monkeypatch.setattr(
        native_kit.faulthandler,
        "dump_traceback_later",
        lambda delay, **kw: watchdog.append((delay, kw["exit"])),
    )
    monkeypatch.setattr(
        native_kit.faulthandler, "cancel_dump_traceback_later", lambda: watchdog.append("cancelled")
    )
    with pytest.raises(RuntimeError, match="native scene failed"):
        try:
            raise RuntimeError("native scene failed")
        finally:
            native_kit.close_native_app(app)
    assert app.closed
    assert watchdog == [(60, True), "cancelled"]
    assert "native scene failed" in capsys.readouterr().err


def test_scene_failure_is_recorded_and_raised_after_graceful_close(cache, monkeypatch, tmp_path):
    from academy import native_image_probe, native_isaac

    app, _ = fake_runtime(monkeypatch, cache / "academy-kit")
    monkeypatch.setattr(native_isaac, "activate", lambda _: None)
    monkeypatch.setitem(sys.modules, "gymnasium", ModuleType("gymnasium"))
    monkeypatch.setitem(sys.modules, "numpy", ModuleType("numpy"))
    monkeypatch.setitem(sys.modules, "matterix_tasks", ModuleType("matterix_tasks"))
    tasks = ModuleType("isaaclab_tasks.utils")

    def fail(*args, **kwargs):
        raise RuntimeError("native scene configuration failed")

    tasks.parse_env_cfg = fail
    monkeypatch.setitem(sys.modules, "isaaclab_tasks.utils", tasks)
    config, output = tmp_path / "config.json", tmp_path / "result.json"
    config.write_text(
        json.dumps(
            {"matterix_root": str(tmp_path / "engine"), "assets_data_dir": str(tmp_path / "assets")}
        )
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["probe", "--confirm-native-probe", "--config", str(config), "--output", str(output)],
    )
    with pytest.raises(RuntimeError, match="native scene configuration failed"):
        native_image_probe.main()
    assert app.closed
    report = json.loads(output.read_text())
    assert report["scene_render_ready"] is False
    assert not report["workflow_verified"] and not report["worker_qualified"]


@pytest.mark.parametrize("failed", [False, True])
def test_studio_cli_persists_result_after_native_close(cache, monkeypatch, tmp_path, failed):
    from academy import native_studio_isaac

    app, _ = fake_runtime(monkeypatch, cache / "academy-kit")

    def native_run(folder, *, probe):
        assert probe
        launched = native_kit.launch_native_app(headless=True)
        try:
            if failed:
                raise RuntimeError("fixture native startup failure")
            (folder / "studio-probe.json").write_text(json.dumps({"passed": True}))
        finally:
            native_kit.close_native_app(launched)

    monkeypatch.setattr(native_studio_isaac, "run", native_run)
    config, output = tmp_path / "config.json", tmp_path / "result.json"
    config.write_text(json.dumps({"engine_version": "e" * 40, "asset_version": "a" * 40}))
    monkeypatch.setattr(
        sys, "argv", ["studio", "--probe", "--config", str(config), "--output", str(output)]
    )
    if failed:
        with pytest.raises(SystemExit, match="did not pass"):
            native_studio_isaac.main()
    else:
        native_studio_isaac.main()
    assert app.closed
    report = json.loads(output.read_text())
    assert report["passed"] is (not failed)
    if failed:
        assert report["error"] == "fixture native startup failure"


@pytest.mark.parametrize(
    "ending,status",
    [
        ("pass", 0),
        ("raise RuntimeError('native failed')", 1),
        ("raise SystemExit('probe failed')", 1),
        ("raise SystemExit(7)", 7),
        ("raise KeyboardInterrupt()", 130),
    ],
)
def test_native_child_exits_after_saving_result_despite_extension_thread(tmp_path, ending, status):
    output = tmp_path / "result.json"
    script = "\n".join(
        [
            "import threading, sys",
            "from pathlib import Path",
            "from academy.native_kit import run_native_cli",
            "def main():",
            "    threading.Thread(target=threading.Event().wait, daemon=False).start()",
            "    Path(sys.argv[1]).write_text('saved after native teardown')",
            "    print('result saved', flush=False)",
            "    " + ending,
            "run_native_cli(main)",
        ]
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(output)],
        capture_output=True,
        text=True,
        timeout=5,
        env=os.environ | {"PYTHONPATH": str(Path(native_kit.__file__).resolve().parents[1])},
    )
    assert result.returncode == status
    assert output.read_text() == "saved after native teardown"
    assert result.stdout == "result saved\n"
    if "native failed" in ending:
        assert "RuntimeError: native failed" in result.stderr
    if "probe failed" in ending:
        assert "probe failed" in result.stderr


def test_camera_pose_reaches_renderer_without_a_viewport(monkeypatch):
    calls = []
    module = ModuleType("isaacsim.core.rendering_manager")
    module.ViewportManager = SimpleNamespace(set_camera_view=lambda *a, **kw: calls.append((a, kw)))
    monkeypatch.setitem(sys.modules, module.__name__, module)
    env = SimpleNamespace(
        num_envs=1,
        cfg=SimpleNamespace(
            viewer=SimpleNamespace(
                origin_type="env",
                env_index=0,
                cam_prim_path="/OmniverseKit_Persp",
                eye=(0.42, -1.10, 0.8),
                lookat=(0, 0.3, 0.4),
            )
        ),
        scene=SimpleNamespace(env_origins=[SimpleNamespace(tolist=lambda: [1, 2, 3])]),
    )
    native_kit.configure_native_camera(env)
    assert calls[0][0] == ("/OmniverseKit_Persp",)
    assert calls[0][1]["eye"] == pytest.approx([1.42, 0.9, 3.8])
    assert calls[0][1]["target"] == pytest.approx([1, 2.3, 3.4])
    env.num_envs = 2
    with pytest.raises(RuntimeError, match="single-environment"):
        native_kit.configure_native_camera(env)
    assert len(calls) == 1
