"""Keep Kit's mutable runtime files outside the independent, read-only code trees."""

import argparse
import faulthandler
import json
import os
import stat
import sys
import tempfile
import traceback
from pathlib import Path


def _writable_directory(path):
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise RuntimeError("Kit runtime directory must belong to the current worker")
    if info.st_mode & 0o022:
        raise RuntimeError("Kit runtime directory must not be writable by other users")
    # Check real filesystem access, including read-only mounts, before importing Isaac.
    with tempfile.TemporaryFile(dir=path) as stream:
        stream.write(b"academy-kit-write-check")
        stream.flush()


def prepare_kit_root(protected_roots=()):
    base = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
    root = base / "academy-kit"
    # Lab's kit_args implementation splits on whitespace rather than shell quoting.
    # Reject ambiguous input instead of sending a partial path to Kit.
    if not root.is_absolute() or any(char.isspace() for char in str(root)):
        raise RuntimeError("Kit cache requires an absolute path without whitespace")
    if root != root.resolve():
        raise RuntimeError("Kit cache must not traverse symlinks or parent references")
    protected = (sys.prefix, Path(__file__).resolve().parents[3], *protected_roots)
    if any(root.is_relative_to(Path(path).resolve()) for path in protected):
        raise RuntimeError("Kit cache must be outside installed code and source trees")
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    _writable_directory(base)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root != root.resolve():
        raise RuntimeError("Kit cache path changed while preparing it")
    _writable_directory(root)
    root.chmod(0o700)
    return root


def verify_kit_paths(root, tokens):
    paths = {}
    for name in ("cache", "data", "logs", "omni_cache", "omni_data", "omni_logs"):
        path = Path(tokens.resolve("${" + name + "}"))
        if not path.is_absolute() or not path.is_relative_to(root) or path != path.resolve():
            raise RuntimeError("Kit " + name + " token escaped the private runtime directory")
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        _writable_directory(path)
        paths[name] = str(path)
    return paths


def launch_native_app(*, headless, protected_roots=()):
    root = prepare_kit_root(protected_roots)
    from isaaclab.app import AppLauncher

    parser = argparse.ArgumentParser()
    AppLauncher.add_app_launcher_args(parser)
    flags = ["--enable_cameras", "--device", "cuda:0", "--viz", "kit", "--livestream", "0"]
    if headless:
        flags += ["--headless"]
    flags += ["--kit_args=--portable --portable-root " + str(root)]
    # Kit's default fast shutdown terminates Python with status 0 inside close().
    # Academy must return to its caller to persist probe results and propagate errors.
    app = AppLauncher(parser.parse_args(flags), fast_shutdown=False).app
    try:
        import carb.tokens

        paths = verify_kit_paths(root, carb.tokens.get_tokens_interface())
        print("ACADEMY_KIT_PATHS=" + json.dumps(paths, sort_keys=True), flush=True)
    except BaseException:
        close_native_app(app)
        raise
    return app


def close_native_app(app):
    """Keep errors visible and bound graceful Kit teardown, including C-level hangs."""
    if sys.exception() is not None:
        traceback.print_exc()
    sys.stdout.flush()
    sys.stderr.flush()
    faulthandler.dump_traceback_later(60, exit=True, file=sys.__stderr__)
    try:
        app.close()
    finally:
        faulthandler.cancel_dump_traceback_later()
