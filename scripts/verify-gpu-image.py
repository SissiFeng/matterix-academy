"""Validate the actual Packer plugin schema with isolated fake inputs and blocked AWS access."""

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packer", required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="academy-packer-validate-") as temp:
        root = Path(temp)
        text = (ROOT / "ops/ec2-gpu/image/gpu.pkr.hcl").read_text()
        text = text.replace(
            'source "amazon-ebs" "internal_flex" {',
            'source "amazon-ebs" "internal_flex" {\n'
            "  skip_credential_validation = true\n"
            "  skip_metadata_api_check = true\n"
            "  skip_region_validation = true\n",
        )
        (root / "gpu.pkr.hcl").write_text(text)
        for name in ("prepare-gpu.sh", "provision.sh", "finalize.sh"):
            (root / name).write_text("#!/bin/bash\nexit 1\n")
        inputs = root / "input"
        inputs.mkdir()
        for name in (
            "academy.tar.gz",
            "release.json",
            "image-manifest.json",
            "engine.tar.gz",
            "assets.tar.gz",
            "sources.json",
            "nvidia-driver.run",
            "driver.json",
        ):
            (inputs / name).write_bytes(b"offline synthetic schema fixture")
        values = {
            "confirm_paid_build": True,
            "accept_nvidia_eula": True,
            "expected_account_id": "000000000000",
            "source_ami": "ami-00000000000000000",
            "vpc_id": "vpc-00000000000000000",
            "subnet_id": "subnet-00000000000000000",
            "ssh_cidr": "127.0.0.1/32",
            "input_dir": str(inputs),
            "release_sha256": "a" * 64,
            "manifest_sha256": "b" * 64,
        }
        variables = root / "offline.pkrvars.json"
        variables.write_text(json.dumps(values))
        env = {key: value for key, value in os.environ.items() if not key.startswith("AWS_")}
        env.update(
            AWS_ACCESS_KEY_ID="offline-only",
            AWS_SECRET_ACCESS_KEY="offline-only",
            AWS_EC2_METADATA_DISABLED="true",
            HTTP_PROXY="http://127.0.0.1:9",
            HTTPS_PROXY="http://127.0.0.1:9",
            http_proxy="http://127.0.0.1:9",
            https_proxy="http://127.0.0.1:9",
            NO_PROXY="",
            no_proxy="",
        )
        subprocess.run(
            [args.packer, "validate", "-var-file=" + str(variables), str(root)],
            env=env,
            check=True,
            timeout=45,
        )
    print("Packer plugin schema verified with fake inputs and blocked cloud access; no build ran.")


if __name__ == "__main__":
    main()
