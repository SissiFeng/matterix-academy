"""Execute only finalization's diagnostic tail with local probe/capacity fixtures."""

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


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
