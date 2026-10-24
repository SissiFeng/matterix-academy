#!/usr/bin/env python3
"""Build a self-contained local companion candidate; never publishes or installs."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if platform.system() not in {"Darwin", "Linux"}:
        parser.error("This release packages macOS/Linux only")
    output = args.output.resolve()
    if output.exists():
        parser.error("Choose a new output directory; published packages are immutable")
    output.mkdir(parents=True)
    build = output / "build"
    build.mkdir()
    source_root = build / "source"
    shutil.copytree(
        ROOT / "app/backend/academy",
        source_root / "academy",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    entry = build / "entry.py"
    entry.write_text(
        "from academy.companion.__main__ import cli\nif __name__ == '__main__':\n    raise SystemExit(cli())\n"
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--name",
            "academy-bridge",
            "--paths",
            str(source_root),
            "--distpath",
            str(build / "dist"),
            "--workpath",
            str(build / "work"),
            "--specpath",
            str(build),
            "--collect-submodules",
            "academy.companion",
            "--copy-metadata",
            "grpcio",
            str(entry),
        ],
        check=True,
        cwd=ROOT,
    )
    binary = build / "dist/academy-bridge"
    subprocess.run([str(binary), "--help"], check=True, capture_output=True)
    subprocess.run([str(binary), "doctor"], check=True, capture_output=True)
    payload = output / "Academy Bridge"
    payload.mkdir()
    shutil.copy2(binary, payload / "academy-bridge")
    launcher = payload / (
        "Start Academy Bridge.command"
        if platform.system() == "Darwin"
        else "start-academy-bridge.sh"
    )
    launcher.write_text("""#!/bin/sh
set -eu
umask 077
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
printf 'Academy Bridge — supervised instrument connection\n\n'
printf '\n1 Pair this computer\n2 Read-only instrument check\n3 Wait for browser workflows (each run needs local confirmation)\n4 Install a reviewed Flex connector (changes robot services)\n5 Check this Mac runtime only\nSelect 1, 2, 3, 4 or 5: '
IFS= read -r choice
if [ "$choice" = 5 ]; then
  exec "$here/academy-bridge" doctor
fi
if [ "$choice" = 4 ]; then
  printf 'Private lab-approved installation request: '
  IFS= read -r request
  printf 'Private approved installation recipe: '
  IFS= read -r recipe
  printf 'Local AC connector source repository: '
  IFS= read -r source
  printf 'Approved downloaded connector archive: '
  IFS= read -r archive
  exec "$here/academy-bridge" setup install --request "$request" --recipe "$recipe" --source-repo "$source" --archive "$archive"
fi
printf 'Path to the lab-approved private configuration file: '
IFS= read -r config
test -f "$config" || { printf 'Configuration file not found.\n'; exit 1; }
case "$choice" in
  1) exec "$here/academy-bridge" pair --config "$config" ;;
  2) exec "$here/academy-bridge" probe --config "$config" ;;
  3) exec "$here/academy-bridge" run --config "$config" ;;
  *) printf 'No action selected.\n' ;;
esac
""")
    launcher.chmod(0o755)
    (payload / "README.txt").write_text(
        "ACADEMY BRIDGE — LOCAL BUILD CANDIDATE\n\n"
        "This bundle includes its Python runtime. No Python installation is needed.\n"
        "Open the launcher after reviewing the source and your operating system's consent.\n"
        "Provide the private lab-approved connection/profile file (mode 0600).\n"
        "Pair using the single-use code from Sim → Real → Connect an instrument.\n"
        "Connecting or checking does not move the robot. Each physical run needs a local operator.\n\n"
        "This local build is not an Apple-notarized installer or a qualified robot connector.\n"
        "The separate reviewed Flex installer requires a qualified recipe and explicit local consent.\n"
        "It does not replace robot firmware, create a hardware qualification or copy SSH credentials to AWS.\n"
        "Robot-side deployment and calibration must be qualified separately.\n"
    )
    (payload / "BUILD-DEPENDENCIES.json").write_text(
        json.dumps(
            {
                "scope": "Build environment; not every distribution is included in the executable",
                "python": platform.python_version(),
                "uv_lock_sha256": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest(),
                "packages": sorted(
                    [
                        {"name": d.metadata["Name"], "version": d.version}
                        for d in importlib.metadata.distributions()
                    ],
                    key=lambda p: p["name"].lower(),
                ),
            },
            indent=2,
        )
        + "\n"
    )
    source_hash = hashlib.sha256()
    for source in sorted((source_root / "academy").rglob("*.py")):
        source_hash.update(
            str(source.relative_to(source_root)).encode() + b"\0" + source.read_bytes()
        )
    manifest = {
        "schema": "academy.companion-build/1",
        "status": "candidate",
        "version": "0.2.0",
        "platform": "macos" if platform.system() == "Darwin" else "linux",
        "architecture": platform.machine(),
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "source_tree_sha256": source_hash.hexdigest(),
        "source_dirty": bool(
            subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()
        ),
        "packaging_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "notarized": False,
        "hardware_qualified": False,
        "files": {
            str(p.relative_to(payload)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(payload.iterdir())
            if p.is_file()
        },
    }
    (payload / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    archive = output / f"academy-bridge-{manifest['platform']}-{manifest['architecture']}.zip"
    with ZipFile(archive, "x", ZIP_DEFLATED) as zipfile:
        for path in sorted(payload.rglob("*")):
            if path.is_file():
                zipfile.write(path, path.relative_to(output))
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    result = {
        "archive": str(archive),
        "sha256": checksum,
        "size_bytes": archive.stat().st_size,
        "help_check_passed": True,
        "runtime_doctor_passed": True,
        "published": False,
        "installed": False,
        **manifest,
    }
    (output / "build-result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "files"}, indent=2))


if __name__ == "__main__":
    os.umask(0o077)
    main()
