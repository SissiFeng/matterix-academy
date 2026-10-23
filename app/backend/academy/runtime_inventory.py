"""Read-only internal Flex source/runtime fingerprint. Never installs or starts Isaac."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import zipfile
from pathlib import Path

PROFILE = {
    "engine_repository": "ac-rad/Matterix-Internal",
    "engine_commit": "18a96b78ee989fbf4e480e9db6a588c148c6adbe",
    "asset_repository": "ac-rad/Matterix_assets_internal",
    "asset_commit": "c57f12a04079a5f99405e1fcb818a3b7ccc52e5b",
    "isaaclab_source_commit": "ffff603eafc6b74264a5261cc0183d6a65390d78",
    "driver_version": "595.58.03",
    "python_version": "3.12",
    "isaaclab_version": "3.0.0b2.post1",
    "isaacsim_version": "6.0.1.0",
    "torch_version": "2.11.0+cu128",
    "torchvision_version": "0.26.0+cu128",
    "isaaclab_wheel_sha256": "dd32886588479ffd70f7348019aeac1582eb9ad16c40244f41d9f458f96f73c3",
}
REQUIRED_CHECKS = {
    "engine_pin",
    "assets_pin",
    "fixed_scene_source",
    "asset_payloads_materialized",
    "runtime_versions",
    "isaaclab_artifact",
    "linux_x86_64",
    "launcher_arguments",
    "pip_check",
    "gpu_present",
    "driver_version",
}
PROBE = """import importlib.metadata as m, importlib.util as u, json, platform, sys, argparse, subprocess
from academy.runtime_inventory import verify_installed_isaaclab
proof=verify_installed_isaaclab()
if not proof['verified']: raise RuntimeError('Installed Isaac Lab differs from the pinned publisher wheel')
p={}
for n in ("isaaclab","isaacsim","torch","torchvision","isaaclab_physx"):
 try: p[n]=m.version(n)
 except m.PackageNotFoundError: p[n]=None
from isaaclab.app import AppLauncher
parser=argparse.ArgumentParser()
AppLauncher.add_app_launcher_args(parser)
parser.parse_args(["--enable_cameras","--device","cuda:0","--viz","kit","--livestream","0","--headless"])
checked=subprocess.run([sys.executable,"-m","pip","check"],capture_output=True,text=True,timeout=45)
print(json.dumps({"isaaclab_artifact":proof,"launcher_arguments":True,"pip_check":checked.returncode==0,"python":platform.python_version(),"os":platform.system(),"machine":platform.machine(),"packages":p,"physx":u.find_spec("isaaclab_physx") is not None}))
"""


def verify_installed_isaaclab(
    wheel=Path("/etc/academy-native/evidence/isaaclab.whl"), distribution=None
):
    """Compare installed bytes with the hash-pinned publisher wheel before importing Lab."""
    from importlib.metadata import distribution as installed_distribution

    result = {"verified": False, "wheel_sha256": None, "files_checked": 0}
    try:
        with wheel.open("rb") as file:
            result["wheel_sha256"] = hashlib.file_digest(file, "sha256").hexdigest()
        if result["wheel_sha256"] != PROFILE["isaaclab_wheel_sha256"]:
            return result
        distribution = distribution or installed_distribution("isaaclab")
        with zipfile.ZipFile(wheel) as archive:
            for member in archive.infolist():
                if member.is_dir() or member.filename.endswith(".dist-info/RECORD"):
                    continue  # Installers rewrite RECORD, not the wheel's code/metadata bytes.
                path = Path(member.filename)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or any(part.endswith(".data") for part in path.parts)
                ):
                    return result
                installed = Path(distribution.locate_file(member.filename))
                if (
                    hashlib.sha256(installed.read_bytes()).digest()
                    != hashlib.sha256(archive.read(member)).digest()
                ):
                    return result
                result["files_checked"] += 1
        result["verified"] = result["files_checked"] > 0
    except (OSError, ValueError, ModuleNotFoundError, zipfile.BadZipFile):
        pass
    return result


def git(root, *args):
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True, stderr=subprocess.DEVNULL
    ).strip()


def source_tree_clean(root, expected_commit):
    """Read Git objects and materialized bytes directly; never run an LFS clean filter."""
    root = Path(root)
    try:
        if git(root, "rev-parse", "HEAD") != expected_commit:
            return False
        # Validate object identities before trusting the tree and its LFS pointer blobs.
        subprocess.run(
            ["git", "-C", str(root), "fsck", "--full", "--no-reflogs", "--no-dangling"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if git(root, "ls-files", "--others", "--exclude-standard", "-z"):
            return False
        records = git(root, "ls-tree", "-rlz", "HEAD").split("\0")
        for record in records:
            if not record:
                continue
            header, relative = record.split("\t", 1)
            mode, kind, oid, size = header.split()
            if kind == "commit" and relative == "source/matterix_assets/data":
                continue  # Historical gitlink is replaced by the separately pinned assets root.
            path = root / relative
            if (
                kind != "blob"
                or mode not in {"100644", "100755"}
                or path.is_symlink()
                or not path.is_file()
            ):
                return False
            if bool(path.stat().st_mode & 0o111) != (mode == "100755"):
                return False
            pointer = None
            if int(size) <= 1024:
                blob = subprocess.check_output(["git", "-C", str(root), "cat-file", "blob", oid])
                pointer = re.fullmatch(
                    rb"version https://git-lfs.github.com/spec/v1\noid sha256:([a-f0-9]{64})\nsize ([0-9]+)\n?",
                    blob,
                )
            with path.open("rb") as file:
                if pointer:
                    if (
                        path.stat().st_size != int(pointer[2])
                        or hashlib.file_digest(file, "sha256").hexdigest() != pointer[1].decode()
                    ):
                        return False
                else:
                    hasher = hashlib.sha1(f"blob {path.stat().st_size}\0".encode())
                    for block in iter(lambda: file.read(1024 * 1024), b""):
                        hasher.update(block)
                    if hasher.hexdigest() != oid:
                        return False
        return True
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def source_inventory(engine, assets):
    result = {"profile": PROFILE, "checks": {}, "issues": [], "sources": {}}
    for name, root, expected in (
        ("engine", engine, PROFILE["engine_commit"]),
        ("assets", assets, PROFILE["asset_commit"]),
    ):
        try:
            head = git(root, "rev-parse", "HEAD")
            clean = source_tree_clean(root, expected)
            result["sources"][name] = {"commit": head, "clean": clean}
            result["checks"][name + "_pin"] = clean and head == expected
            if not result["checks"][name + "_pin"]:
                result["issues"].append(
                    f"{name}: use the clean, exact internal Flex profile commit"
                )
        except (OSError, subprocess.SubprocessError):
            result["checks"][name + "_pin"] = False
            result["issues"].append(f"{name}: readable Git checkout required")
    task = engine / "source/matterix_tasks/matterix_tasks/test_dev_tasks/matterix_flex_mixing.py"
    result["checks"]["fixed_scene_source"] = task.is_file() and "mix_four_vials" in task.read_text()
    # LFS pointer stubs cannot establish available renderable payloads.
    payloads = []
    try:
        for relative in git(assets, "ls-files").splitlines():
            path = assets / relative
            if path.is_file() and path.suffix.lower() in {".usd", ".usda", ".usdc", ".usdz"}:
                with path.open("rb") as stream:
                    if stream.read(100).startswith(b"version https://git-lfs.github.com/spec/"):
                        payloads.append(relative)
        result["checks"]["asset_payloads_materialized"] = not payloads
        result["lfs_pointer_count"] = len(payloads)
    except (OSError, subprocess.SubprocessError):
        result["checks"]["asset_payloads_materialized"] = False
    return result


def collect(engine, assets, python):
    result = source_inventory(engine, assets)
    try:
        probe = subprocess.run(
            [str(python), "-c", PROBE],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
            env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
        )
        runtime = json.loads(probe.stdout.strip().splitlines()[-1])
        result["runtime"] = runtime
        result["checks"]["launcher_arguments"] = runtime.get("launcher_arguments") is True
        result["checks"]["pip_check"] = runtime.get("pip_check") is True
        artifact = runtime.get("isaaclab_artifact", {})
        result["checks"]["isaaclab_artifact"] = (
            artifact.get("verified") is True
            and artifact.get("wheel_sha256") == PROFILE["isaaclab_wheel_sha256"]
            and artifact.get("files_checked", 0) > 0
        )
        versions = runtime["packages"]
        result["checks"]["runtime_versions"] = (
            runtime["python"].startswith("3.12.")
            and all(
                versions[name] == PROFILE[key]
                for name, key in (
                    ("isaaclab", "isaaclab_version"),
                    ("isaacsim", "isaacsim_version"),
                    ("torch", "torch_version"),
                    ("torchvision", "torchvision_version"),
                )
            )
            and runtime["physx"]
        )
        result["checks"]["linux_x86_64"] = (
            runtime["os"] == "Linux" and runtime["machine"] == "x86_64"
        )
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError):
        result["checks"].update(runtime_versions=False, linux_x86_64=False, isaaclab_artifact=False)
        result["issues"].append("Pinned Isaac Python environment could not be verified")
    try:
        gpu = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        result["gpu"] = gpu.stdout.strip()
        devices = result["gpu"].splitlines()
        parts = [part.strip() for part in devices[0].split(",")] if len(devices) == 1 else []
        result["checks"]["gpu_present"] = (
            len(parts) == 3
            and parts[0] in {"NVIDIA L4", "NVIDIA L40S"}
            and int(parts[2].split()[0]) >= 22000
        )
        result["checks"]["driver_version"] = (
            len(parts) == 3 and parts[1] == PROFILE["driver_version"]
        )
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        result["checks"]["gpu_present"] = False
        result["issues"].append("No NVIDIA driver/GPU was observed on this host")
    result["ready_for_commissioning"] = REQUIRED_CHECKS <= result["checks"].keys() and all(
        result["checks"].values()
    )
    result["native_verified"] = False
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine-root", required=True, type=Path)
    parser.add_argument("--assets-root", required=True, type=Path)
    parser.add_argument("--isaac-python", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = collect(
        args.engine_root.resolve(), args.assets_root.resolve(), args.isaac_python.resolve()
    )
    report["profile_sha256"] = hashlib.sha256(
        json.dumps(PROFILE, sort_keys=True).encode()
    ).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print("Runtime inventory saved; native execution is still unverified.")
    raise SystemExit(0 if report["ready_for_commissioning"] else 2)


if __name__ == "__main__":
    main()
