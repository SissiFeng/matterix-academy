"""Check all eight local image inputs before any paid build. Does not invoke Packer or AWS."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    sha = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def validate(root):
    spec = importlib.util.spec_from_file_location("manifest", ROOT / "scripts/ec2-gpu-prepare.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest = json.loads((root / "image-manifest.json").read_text())
    module.validate_manifest(manifest)
    release = json.loads((root / "release.json").read_text())
    if release["academy_commit"] != manifest["academy_commit"]:
        raise ValueError("Release and image Academy commits differ")
    expected = {
        "academy.tar.gz": release["archive_sha256"],
        "image-manifest.json": release["manifest_sha256"],
    }
    sources = json.loads((root / "sources.json").read_text())
    if set(sources) != {"engine", "assets"}:
        raise ValueError("Require exactly the two independent internal sources")
    for name, key in (("engine", "engine_commit"), ("assets", "asset_commit")):
        if sources[name]["commit"] != manifest[key]:
            raise ValueError("Source pin differs from image manifest")
        expected[name + ".tar.gz"] = sources[name]["sha256"]
    driver = json.loads((root / "driver.json").read_text())
    if driver != json.loads((ROOT / "ops/ec2-gpu/image/driver.json").read_text()):
        raise ValueError("Use the exact reviewed NVIDIA driver artifact")
    expected["nvidia-driver.run"] = driver["sha256"]
    for name, digest in expected.items():
        if sha256(root / name) != digest:
            raise ValueError("Image input checksum mismatch: " + name)
    return {
        "inputs_ready_for_authorized_build": True,
        "academy_commit": release["academy_commit"],
        "archive_sha256": release["archive_sha256"],
        "manifest_sha256": release["manifest_sha256"],
        "image_built": False,
        "browser_dt_accepted": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = validate(args.input_dir.resolve())
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(2, f"Image inputs blocked: {exc}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
