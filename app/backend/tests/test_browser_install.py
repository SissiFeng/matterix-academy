"""Bounded browser installation retries must fail the job when exhausted."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("failed_phase", [None, "install-deps", "install"])
def test_browser_install_retries_transient_failures_and_stops_on_exhaustion(tmp_path, failed_phase):
    root = Path(__file__).resolve().parents[3]
    (tmp_path / "scripts").mkdir()
    (tmp_path / "app/frontend").mkdir(parents=True)
    script = tmp_path / "scripts/install-browser-ci.sh"
    shutil.copy(root / "scripts/install-browser-ci.sh", script)
    binary = tmp_path / "bin"
    binary.mkdir()
    timeout = binary / "timeout"
    timeout.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        "path = pathlib.Path(os.environ['CALL_LOG'])\n"
        "calls = json.loads(path.read_text()) if path.exists() else []\n"
        "args = sys.argv[1:]\n"
        "phase = args[-2]\n"
        "attempt = sum(call[-2] == phase for call in calls) + 1\n"
        "calls.append(args)\n"
        "path.write_text(json.dumps(calls))\n"
        "sys.exit(124 if phase == os.environ.get('FAILED_PHASE') or attempt == 1 else 0)\n"
    )
    timeout.chmod(0o755)
    sleep = binary / "sleep"
    sleep.write_text("#!/bin/sh\nexit 0\n")
    sleep.chmod(0o755)
    log = tmp_path / "calls.json"
    result = subprocess.run(
        ["bash", str(script)],
        env={
            **os.environ,
            "PATH": f"{binary}{os.pathsep}{os.environ['PATH']}",
            "CALL_LOG": str(log),
            "FAILED_PHASE": failed_phase or "",
        },
        text=True,
        capture_output=True,
        check=False,
    )
    calls = json.loads(log.read_text())
    expected_phases = ["install-deps"] * 2
    if failed_phase != "install-deps":
        expected_phases += ["install"] * 2
    assert [call[-2] for call in calls] == expected_phases
    assert all(call[0] == "--kill-after=15s" for call in calls)
    assert all(call[1] == ("300s" if call[-2] == "install-deps" else "120s") for call in calls)
    assert result.returncode == (124 if failed_phase else 0)
    assert (
        "failed (exit 124)"
        in (tmp_path / "build/browser-install-logs/system-dependencies.log").read_text()
    )
