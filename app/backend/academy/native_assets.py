"""Pinned NVIDIA ground assets, prepared over HTTPS and used locally by native children."""

import argparse
import hashlib
import json
import os
import tempfile
import urllib.request
from functools import partial
from pathlib import Path

ROOT_URL = "https://omniverse-content-production.s3-us-west-2.amazonaws.com/Assets/Isaac/6.0/Isaac/Environments/Grid/"
FILES = {
    "default_environment.usd": "78e9a1e72a8838a13d0f65c49cd487ab92e89233cd128b057730b5b5b4ca2164",
    "Materials/Textures/Wireframe_blue.png": "940b96ee8c8e53bd1acbc770d4ca0ac98bed9c96439ab386d1b27dbc9790cc4e",
    "Materials/Textures/WireframeBlur_basecolor.png": "deab39088eaf39ed7be951966c5e6bd5e58b90ab64743b0cdc8e5579fd5a99d9",
    "Materials/Textures/WireframeBlur_blue.png": "44fc0e82007bb0bd94631cd7ec45986a71ed74b9413899fbffac13efe151be4b",
}
MAX_BYTES = 4 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Pinned native assets must not redirect")


def checked_path(root, name):
    root = Path(root)
    path = root / name
    if not root.is_absolute() or root != root.resolve() or path != path.resolve():
        raise ValueError("Native asset cache must be absolute and must not traverse symlinks")
    return path


def verified_ground(root):
    for name, digest in FILES.items():
        path = checked_path(root, name)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError("Pinned NVIDIA asset is missing or changed: " + name)
    return str(checked_path(root, "default_environment.usd"))


def prepare(root):
    """Explicit operator/build action. Never called by a learner run."""
    opener = urllib.request.build_opener(NoRedirect())
    for name, digest in FILES.items():
        path = checked_path(root, name)
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest:
            continue
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with opener.open(ROOT_URL + name, timeout=20) as response:
            payload = response.read(MAX_BYTES + 1)
        if len(payload) > MAX_BYTES or hashlib.sha256(payload).hexdigest() != digest:
            raise RuntimeError("Downloaded NVIDIA asset differs from its pinned SHA256: " + name)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
            os.replace(temporary, path)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
    return verified_ground(root)


def configure_ground(root):
    """Bind the same ground geometry locally without changing independent source files."""
    ground = verified_ground(root)
    from isaaclab.sim.spawners.from_files.from_files_cfg import GroundPlaneCfg
    from matterix.envs import matterix_base_env

    expected = ROOT_URL + "default_environment.usd"
    if GroundPlaneCfg().usd_path != expected:
        raise RuntimeError("The native ground source changed; requalify the asset manifest")
    # The pinned Matterix environment creates this config inside scene construction.
    # Preserve its color, scale, physics material and placement, overriding only the URL.
    matterix_base_env.GroundPlaneCfg = partial(GroundPlaneCfg, usd_path=ground)
    print("ACADEMY_NATIVE_GROUND=" + json.dumps({"path": ground, "files": FILES}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", required=True, action="store_true")
    parser.add_argument("--cache-root", required=True, type=Path)
    args = parser.parse_args()
    print(prepare(args.cache_root))


if __name__ == "__main__":
    main()
