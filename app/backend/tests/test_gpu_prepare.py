"""Exercise the pre-driver reboot lifecycle with local command/filesystem fixtures."""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def host_fixture(tmp_path, *, loaded, initramfs_status=0):
    commands = tmp_path / "bin"
    commands.mkdir()
    module_dir = tmp_path / "modprobe.d"
    module_dir.mkdir()
    release = tmp_path / "os-release"
    release.write_text('ID=ubuntu\nVERSION_ID="24.04"\n')
    log = tmp_path / "commands.log"
    log.touch()
    for name, body in {
        "uname": "printf 'x86_64\\n'",
        "lsmod": "printf 'lsmod\\n' >> \"$GPU_TEST_LOG\"\n"
        + ("printf 'nouveau 123 0\\n'" if loaded else "printf 'Module Size Used_by\\n'"),
        "update-initramfs": 'printf "update-initramfs %s\\n" "$*" >> "$GPU_TEST_LOG"\n'
        + f"exit {initramfs_status}",
        "sync": 'printf "sync\\n" >> "$GPU_TEST_LOG"',
        "reboot": 'printf "reboot\\n" >> "$GPU_TEST_LOG"',
    }.items():
        command = commands / name
        command.write_text("#!/bin/sh\n" + body + "\n")
        command.chmod(0o755)

    def run(source):
        source = (
            source.replace('"$EUID" == 0', f'"$EUID" == {os.getuid()}')
            .replace("/etc/os-release", str(release))
            .replace("/etc/modprobe.d", str(module_dir))
        )
        return subprocess.run(
            ["bash", "-euo", "pipefail", "-c", source],
            env={
                **os.environ,
                "PATH": f"{commands}:{os.environ['PATH']}",
                "GPU_TEST_LOG": str(log),
            },
            capture_output=True,
            text=True,
            timeout=10,
        )

    return run, log, module_dir


@pytest.mark.parametrize("loaded", [False, True])
def test_gpu_preparation_reboots_only_after_blacklist_and_initramfs(tmp_path, loaded):
    run, log, module_dir = host_fixture(tmp_path, loaded=loaded)
    result = run((ROOT / "ops/ec2-gpu/image/prepare-gpu.sh").read_text())
    assert result.returncode == 0, result.stderr
    assert (module_dir / "academy-nouveau.conf").read_text() == (
        "blacklist nouveau\noptions nouveau modeset=0\n"
    )
    assert log.read_text().splitlines() == ["update-initramfs -u", "lsmod"] + (
        ["sync", "reboot"] if loaded else []
    )


def test_gpu_preparation_stops_before_reboot_if_initramfs_update_fails(tmp_path):
    run, log, _ = host_fixture(tmp_path, loaded=True, initramfs_status=7)
    result = run((ROOT / "ops/ec2-gpu/image/prepare-gpu.sh").read_text())
    assert result.returncode == 7
    assert log.read_text().splitlines() == ["update-initramfs -u"]


def test_provision_rejects_persistent_nouveau_before_payload_or_driver(tmp_path):
    run, log, _ = host_fixture(tmp_path, loaded=True)
    script = (ROOT / "ops/ec2-gpu/image/provision.sh").read_text()
    # Exercise the actual entry checks, stopping before any payload path is used.
    result = run(script[: script.index("input=/tmp/academy-image-input")])
    assert result.returncode == 1
    assert "Nouveau is still loaded" in result.stderr
    assert log.read_text().splitlines() == ["lsmod"]


def test_packer_prepares_and_waits_for_reboot_before_any_private_payload():
    config = (ROOT / "ops/ec2-gpu/image/gpu.pkr.hcl").read_text()
    prepare = config.index("${path.root}/prepare-gpu.sh")
    first_file = config.index('provisioner "file"')
    provision = config.index("${path.root}/provision.sh")
    assert prepare < first_file < provision
    stage = config[prepare : config.index("\n  }", prepare)]
    assert "expect_disconnect = true" in stage
    assert 'pause_after       = "30s"' in stage
    reconnect = config[config.index("\n  }", prepare) : first_file]
    assert 'start_retry_timeout = "10m"' in reconnect
