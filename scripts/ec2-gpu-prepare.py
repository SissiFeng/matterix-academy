"""Render fixed-runner configuration offline from a fully pinned image manifest.

This does not build an AMI, enroll or qualify a worker, enable a gate, or call AWS.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app/backend"))
from academy.runtime_inventory import PROFILE

FIELDS = {
    "schema_version",
    "status",
    "worker_id",
    "ubuntu_version",
    "python_version",
    "isaacsim_version",
    "isaaclab_version",
    "isaaclab_source_commit",
    "driver_version",
    "academy_commit",
    "engine_commit",
    "asset_commit",
    "simulation_only",
    "controls",
    "engine_repository",
    "asset_repository",
    "torch_version",
    "torchvision_version",
    "isaaclab_wheel_sha256",
}


def validate_manifest(manifest):
    if set(manifest) != FIELDS:
        raise ValueError("Use the complete image-manifest schema; extra fields are rejected")
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
        raise ValueError("Unsupported image manifest version")
    if manifest["status"] != "prepared-not-qualified" or manifest["simulation_only"] is not True:
        raise ValueError("Preparation must remain unqualified and simulation-only")
    if manifest["controls"] != []:
        raise ValueError("Pause, resume and cancel are not qualified by the fixed native adapter")
    if manifest["ubuntu_version"] not in {"22.04", "24.04"}:
        raise ValueError("Prepare an Ubuntu 22.04 or 24.04 x86_64 image")
    for key in (
        "python_version",
        "isaacsim_version",
        "isaaclab_version",
        "isaaclab_source_commit",
        "engine_repository",
        "asset_repository",
        "torch_version",
        "torchvision_version",
        "isaaclab_wheel_sha256",
        "driver_version",
    ):
        if manifest[key] != PROFILE[key]:
            raise ValueError(f"Internal Flex profile mismatch: {key}")
    if (
        manifest["engine_commit"] != PROFILE["engine_commit"]
        or manifest["asset_commit"] != PROFILE["asset_commit"]
    ):
        raise ValueError("Use the exact reviewed internal Flex engine and asset commits")
    for field in ("academy_commit", "engine_commit", "asset_commit", "isaaclab_source_commit"):
        if not isinstance(manifest[field], str) or not re.fullmatch(
            r"[a-f0-9]{40}", manifest[field]
        ):
            raise ValueError(f"Resolve the exact reviewed {field} before rendering")
    if not isinstance(manifest["worker_id"], str) or not re.fullmatch(
        r"[a-z0-9][a-z0-9-]{0,63}", manifest["worker_id"]
    ):
        raise ValueError("Use a valid worker registry identity")
    if not isinstance(manifest["driver_version"], str) or not re.fullmatch(
        r"[0-9]+\.[0-9]+\.[0-9]+", manifest["driver_version"]
    ):
        raise ValueError("Pin the tested NVIDIA driver version in the prepared image")


def native_config(manifest):
    validate_manifest(manifest)
    return {
        "python": "/opt/matterix-isaac/bin/python",
        "matterix_root": "/srv/matterix",
        "assets_root": "/srv/matterix-assets",
        "assets_data_dir": "/srv/matterix-assets",
        "engine_version": manifest["engine_commit"],
        "asset_version": manifest["asset_commit"],
        "run_root": "/var/lib/academy-native/runs",
        "frame_root": "/run/academy-native/frames",
        "headless": True,
        "display": "",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        raw = args.manifest.read_bytes()
        manifest = json.loads(raw)
        config = native_config(manifest)
    except (OSError, TypeError, ValueError) as exc:
        parser.exit(2, f"Preparation blocked: {exc}\n")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "native-config.json").write_text(json.dumps(config, indent=2) + "\n")
    (args.output_dir / "image-manifest.sha256").write_text(hashlib.sha256(raw).hexdigest() + "\n")
    print(
        "Rendered configuration only. Image build, native qualification and browser evidence are still required."
    )


if __name__ == "__main__":
    main()
