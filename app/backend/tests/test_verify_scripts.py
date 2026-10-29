"""Verification must reject either image script's syntax errors and missing CI tooling."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def verification_copy(tmp_path):
    root = Path(__file__).resolve().parents[3]
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy(root / "scripts/verify.sh", scripts / "verify.sh")
    (scripts / "verify-ec2-gpu.sh").write_text("exit 0\n")
    image = tmp_path / "ops/ec2-gpu/image"
    image.mkdir(parents=True)
    for name in ("provision.sh", "finalize.sh"):
        (image / name).write_text("#!/bin/bash\nexit 0\n")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    # Other build stages are irrelevant to shell parser coverage; no tools/cloud calls run.
    for name in ("uv", "npm", "node", "terraform"):
        command = binaries / name
        command.write_text("#!/bin/sh\nexit 0\n")
        command.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{binaries}{os.pathsep}{os.environ['PATH']}",
        "CI": "",
        "PACKER_BIN": "",
    }
    return scripts / "verify.sh", image, env


@pytest.mark.parametrize("name", ["provision.sh", "finalize.sh"])
def test_each_image_script_is_syntax_checked(verification_copy, name):
    script, image, env = verification_copy
    (image / name).write_text("#!/bin/bash\nif true; then\n")
    result = subprocess.run(["bash", str(script)], env=env, text=True, capture_output=True)
    assert result.returncode != 0
    assert name in result.stderr and "syntax error" in result.stderr


def test_ci_cannot_silently_skip_packer_validation(verification_copy):
    script, _, env = verification_copy
    result = subprocess.run(
        ["bash", str(script)], env={**env, "CI": "true"}, text=True, capture_output=True
    )
    assert result.returncode != 0
    assert "CI must install the pinned Packer" in result.stderr
