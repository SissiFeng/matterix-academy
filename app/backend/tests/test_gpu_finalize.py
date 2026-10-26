"""Run finalization's filesystem setup and diagnostics without a GPU or host changes."""

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def test_finalize_recreates_worker_runtime_directory_after_build_reboot(tmp_path):
    # Provisioning reboots before finalization. Model the fresh volatile /run mount:
    # the disabled worker service has not created its systemd RuntimeDirectory yet.
    runtime = tmp_path / "run/academy-native"
    runtime.parent.mkdir()
    assert not runtime.exists()
    script = (ROOT / "ops/ec2-gpu/image/finalize.sh").read_text()
    setup = script[
        script.index("root=/opt/academy-agent") : script.index("export OMNI_KIT_ACCEPT_EULA")
    ]
    setup = (
        setup.replace("/etc/academy-native/evidence", str(tmp_path / "evidence"))
        .replace("/run/academy-native", str(runtime))
        .replace("-o academy-native -g academy-native", f"-o {os.getuid()} -g {os.getgid()}")
    )
    # Execute the real pre-probe setup with only paths and the service identity mapped
    # to this unprivileged fixture. No inventory, runtime import or service starts.
    subprocess.run(["bash", "-euo", "pipefail", "-c", setup], check=True, timeout=10)
    info = runtime.stat()
    assert info.st_uid == os.getuid() and info.st_gid == os.getgid()
    assert info.st_mode & 0o777 == 0o700
    # Match the prepared NativeConfig path used by the Studio renderer.
    frames = runtime / "frames"
    frames.mkdir(mode=0o700)
    (frames / "probe.rgb").write_bytes(b"local framebuffer fixture")


@pytest.mark.parametrize(
    ("probe_status", "reports", "expected_status"),
    [
        (1, ("scene-render", "studio-probe"), 1),
        (124, ("scene-render",), 1),
        (137, (), 1),
        (0, ("scene-render", "studio-probe"), 0),
        (0, ("scene-render",), 1),
    ],
)
def test_finalize_emits_available_diagnostics_before_capacity_failure(
    tmp_path, probe_status, reports, expected_status
):
    source = tmp_path / "native"
    evidence = tmp_path / "evidence"
    source.mkdir()
    evidence.mkdir()
    for report in reports:
        (source / f"{report}.json").write_text(
            json.dumps({"report": report, "passed": probe_status == 0})
        )
    # The real shell tail runs, while its capacity helper gets deterministic local data.
    package = tmp_path / "academy"
    package.mkdir()
    (package / "__init__.py").touch()
    (package / "native_image_probe.py").write_text(
        "def capacity_report(evidence, status, elapsed):\n"
        "    return {'capacity_probe_passed': status == 0, 'probe_exit_code': status}\n"
    )
    python = tmp_path / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n')
    python.chmod(0o755)
    script = (ROOT / "ops/ec2-gpu/image/finalize.sh").read_text()
    # Exclude installation, GPU execution, metadata access and host cleanup entirely.
    tail = script[script.index("probe_elapsed=$((") : script.index('"$root/.venv/bin/python" - <<')]
    tail = tail.replace("/var/lib/academy-native", str(source)).replace(
        "/etc/academy-native/evidence", str(evidence)
    )
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", tail],
        env={
            **os.environ,
            "root": str(tmp_path),
            "evidence": str(evidence),
            "probe_started": "0",
            "probe_status": str(probe_status),
            "PYTHONPATH": str(tmp_path),
        },
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == expected_status, result.stderr
    capacity = result.stdout.index("ACADEMY_CAPACITY_JSON=")
    for report in reports:
        assert (evidence / f"{report}.json").read_bytes() == (
            source / f"{report}.json"
        ).read_bytes()
        marker = "ACADEMY_" + report.replace("-", "_").upper() + "_JSON="
        assert result.stdout.index(marker) < capacity
    assert "Browser acceptance remains pending" not in result.stdout
