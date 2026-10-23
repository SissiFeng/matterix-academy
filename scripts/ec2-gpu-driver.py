"""Download and checksum the public NVIDIA installer outside Academy; never installs or calls AWS."""

import argparse
import hashlib
import importlib.util
import json
import os
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_INSTALLER_BYTES = 512 * 1024 * 1024
MAX_DOWNLOAD_SECONDS = 900


def download(driver, output):
    sha = hashlib.sha256()
    temporary = None
    deadline = time.monotonic() + MAX_DOWNLOAD_SECONDS
    try:
        with tempfile.NamedTemporaryFile(dir=output, delete=False) as file:
            temporary = Path(file.name)
            with urllib.request.urlopen(driver["url"], timeout=60) as response:
                length = response.headers.get("Content-Length")
                if length is not None and int(length) > MAX_INSTALLER_BYTES:
                    raise ValueError("NVIDIA installer exceeds the download size bound")
                size = 0
                while True:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("NVIDIA installer download exceeded its time bound")
                    # read1 returns currently available data, so a trickle cannot keep
                    # a multi-recv read blocked indefinitely beyond the deadline.
                    block = response.read1(1024 * 1024)
                    if time.monotonic() >= deadline:
                        raise TimeoutError("NVIDIA installer download exceeded its time bound")
                    if not block:
                        break
                    size += len(block)
                    if size > MAX_INSTALLER_BYTES:
                        raise ValueError("NVIDIA installer exceeds the download size bound")
                    sha.update(block)
                    file.write(block)
        if sha.hexdigest() != driver["sha256"]:
            raise ValueError("NVIDIA installer differs from publisher checksum")
        os.replace(temporary, output / "nvidia-driver.run")
        (output / "driver.json").write_text(json.dumps(driver, indent=2) + "\n")
        (output / "driver.json").chmod(0o600)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location(
        "release_inputs", ROOT / "scripts/ec2-gpu-release.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = module.external_output(ROOT, args.output_dir)
    driver = json.loads((ROOT / "ops/ec2-gpu/image/driver.json").read_text())
    download(driver, output)
    print(
        "NVIDIA installer checksum verified. No software installed; license acceptance remains explicit."
    )


if __name__ == "__main__":
    main()
