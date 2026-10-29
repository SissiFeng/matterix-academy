"""Host preflight logic with synthetic process metadata; no real GPU imports."""

import json
import os
import subprocess
import sys
import venv
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from academy import runtime_inventory as inventory


def fixture_runtime():
    return {
        "python": "3.12.10",
        "os": "Linux",
        "machine": "x86_64",
        "physx": True,
        "launcher_arguments": True,
        "pip_check": True,
        "isaaclab_artifact": {
            "verified": True,
            "wheel_sha256": inventory.PROFILE["isaaclab_wheel_sha256"],
            "files_checked": 1,
        },
        "packages": {
            name: inventory.PROFILE[key]
            for name, key in (
                ("isaaclab", "isaaclab_version"),
                ("isaacsim", "isaacsim_version"),
                ("torch", "torch_version"),
                ("torchvision", "torchvision_version"),
            )
        },
    }


def collect(monkeypatch, tmp_path, runtime, gpu="NVIDIA L4, 595.58.03, 23034 MiB\n"):
    monkeypatch.setattr(
        inventory,
        "source_inventory",
        lambda *_: {
            "profile": inventory.PROFILE,
            "checks": {
                key: True
                for key in (
                    "engine_pin",
                    "assets_pin",
                    "fixed_scene_source",
                    "asset_payloads_materialized",
                )
            },
            "issues": [],
        },
    )
    monkeypatch.setattr(
        inventory.subprocess,
        "run",
        lambda argv, **_: SimpleNamespace(
            stdout=gpu if argv[0] == "nvidia-smi" else json.dumps(runtime)
        ),
    )
    return inventory.collect(tmp_path, tmp_path, tmp_path / "python")


def test_complete_profile_is_only_ready_to_commission_not_native_acceptance(monkeypatch, tmp_path):
    result = collect(monkeypatch, tmp_path, fixture_runtime())
    assert result["ready_for_commissioning"]
    assert result["native_verified"] is False


@pytest.mark.parametrize("name", ["NVIDIA A10G", "NVIDIA L4", "NVIDIA L40S"])
def test_full_rtx_candidate_still_requires_native_commissioning(monkeypatch, tmp_path, name):
    result = collect(monkeypatch, tmp_path, fixture_runtime(), f"{name}, 595.58.03, 22888 MiB\n")
    assert result["ready_for_commissioning"]
    assert result["native_verified"] is False


@pytest.mark.parametrize("name", ["Tesla T4", "NVIDIA T4"])
def test_t4_candidate_accepts_reserved_device_memory_but_requires_native_probes(
    monkeypatch, tmp_path, name
):
    result = collect(monkeypatch, tmp_path, fixture_runtime(), f"{name}, 595.58.03, 15360 MiB\n")
    assert result["ready_for_commissioning"]
    assert result["native_verified"] is False


@pytest.mark.parametrize(
    "gpu",
    [
        "NVIDIA A10G, 595.58.03, 16384 MiB\n",
        "Tesla T4, 595.58.03, 15359 MiB\n",
        "NVIDIA T4, 595.58.03, 8192 MiB\n",
        "NVIDIA L4, 595.58.03, 15360 MiB\n",
        "NVIDIA A10G, 550.54.14, 22888 MiB\n",
        "NVIDIA A100, 595.58.03, 81920 MiB\n",
        "NVIDIA A10G, 595.58.03, 22888 MiB\nNVIDIA A10G, 595.58.03, 22888 MiB\n",
    ],
)
def test_candidate_gpu_must_keep_memory_driver_and_single_device_gates(monkeypatch, tmp_path, gpu):
    assert not collect(monkeypatch, tmp_path, fixture_runtime(), gpu)["ready_for_commissioning"]


@pytest.mark.parametrize("change", ["python", "lab", "physx", "os", "launcher", "pip", "artifact"])
def test_wrong_generation_or_failed_environment_checks_block_commissioning(
    monkeypatch, tmp_path, change
):
    runtime = deepcopy(fixture_runtime())
    if change == "python":
        runtime["python"] = "3.11.10"
    elif change == "lab":
        runtime["packages"]["isaaclab"] = "2.3.0"
    elif change == "physx":
        runtime["physx"] = False
    elif change == "os":
        runtime["os"] = "Darwin"
    elif change == "launcher":
        runtime["launcher_arguments"] = False
    elif change == "artifact":
        runtime["isaaclab_artifact"]["verified"] = False
    else:
        runtime["pip_check"] = False
    assert not collect(monkeypatch, tmp_path, runtime)["ready_for_commissioning"]


def test_inventory_cli_preserves_symlinked_virtual_environment(monkeypatch, tmp_path):
    selected = tmp_path / "selected-runtime"
    venv.EnvBuilder(with_pip=False, symlinks=True).create(selected)
    python = selected / "bin/python"
    assert python.is_symlink()
    observed = []

    def execute_selected_interpreter(engine, assets, executable):
        result = subprocess.run(
            [str(executable), "-I", "-c", "import sys; print(sys.prefix)"],
            check=True,
            capture_output=True,
            text=True,
        )
        observed.append(result.stdout.strip())
        return {"ready_for_commissioning": observed[-1] == str(selected)}

    monkeypatch.setattr(inventory, "collect", execute_selected_interpreter)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runtime_inventory",
            "--engine-root",
            str(tmp_path),
            "--assets-root",
            str(tmp_path),
            "--isaac-python",
            str(python),
            "--output",
            str(tmp_path / "inventory.json"),
        ],
    )
    with pytest.raises(SystemExit) as result:
        inventory.main()
    assert result.value.code == 0
    assert observed == [str(selected)]


@pytest.mark.parametrize("timeout", [False, True])
def test_runtime_failure_retains_bounded_redacted_stderr(monkeypatch, tmp_path, timeout):
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "fixture-private-environment-value")
    stderr = (
        "x" * 6000
        + "\nAWS_SECRET_ACCESS_KEY=fixture-private-environment-value\n"
        + "Authorization: Bearer fixture-bearer-value\n"
        + "token=fixture-token-value\n"
        + "https://fixture.invalid/path?X-Amz-Signature=fixture-signature\n"
        + "ModuleNotFoundError: No module named 'isaaclab'\n"
    )
    monkeypatch.setattr(
        inventory,
        "source_inventory",
        lambda *_: {"profile": inventory.PROFILE, "checks": {}, "issues": []},
    )

    def fail_runtime(argv, **kwargs):
        if argv[0] == "nvidia-smi":
            return SimpleNamespace(stdout="Tesla T4, 595.58.03, 15360 MiB\n")
        if timeout:
            raise subprocess.TimeoutExpired(argv, 60, stderr=stderr.encode())
        raise subprocess.CalledProcessError(1, argv, stderr=stderr)

    monkeypatch.setattr(inventory.subprocess, "run", fail_runtime)
    report = inventory.collect(tmp_path, tmp_path, tmp_path / "python")
    assert not report["ready_for_commissioning"]
    diagnostic = report["runtime_error"]
    assert diagnostic["type"] == ("TimeoutExpired" if timeout else "CalledProcessError")
    assert "ModuleNotFoundError: No module named 'isaaclab'" in diagnostic["stderr_tail"]
    assert len(diagnostic["stderr_tail"]) <= 4096
    assert not any(
        secret in json.dumps(diagnostic)
        for secret in (
            "fixture-private-environment-value",
            "fixture-bearer-value",
            "fixture-token-value",
            "fixture-signature",
        )
    )


def probe_fixture(failure="", pip_status=0):
    """Exercise the actual child entry point using synthetic runtime dependencies."""
    return f"""
import sys, types, time
from academy import runtime_inventory as inventory
inventory.verify_installed_isaaclab = lambda: {{"verified": {failure != "artifact"!r}}}
inventory.importlib.metadata.version = lambda name: "fixture-version"
inventory.importlib.util.find_spec = lambda name: object()
def pip_check(argv, **kwargs):
    assert argv == [sys.executable, "-m", "pip", "check"]
    assert kwargs["timeout"] == inventory.PIP_CHECK_TIMEOUT_SECONDS
    return types.SimpleNamespace(
        returncode={pip_status},
        stdout="x" * 6000 + "fixture-package requires missing-dependency token=fixture-private-token",
        stderr="Authorization: Bearer fixture-private-bearer",
    )
inventory.subprocess.run = pip_check
class Launcher:
    @staticmethod
    def add_app_launcher_args(parser):
        if {failure == "arguments"!r}:
            raise RuntimeError("Fixture unsupported launcher arguments")
        parser.add_argument("--enable_cameras", action="store_true")
        parser.add_argument("--headless", action="store_true")
        for name in ("device", "viz", "livestream"):
            parser.add_argument("--" + name)
module = types.ModuleType("isaaclab.app")
def delayed_import(name):
    if name == "AppLauncher":
        time.sleep(30)
        return Launcher
    raise AttributeError(name)
if {failure == "timeout"!r}:
    module.__getattr__ = delayed_import
else:
    module.AppLauncher = Launcher
sys.modules["isaaclab"] = types.ModuleType("isaaclab")
sys.modules["isaaclab.app"] = module
"""


@pytest.mark.parametrize("pip_status", [0, 1])
def test_runtime_child_reports_separate_stages_without_dropping_pip_gate(pip_status):
    completed = subprocess.run(
        [sys.executable, "-c", probe_fixture(pip_status=pip_status) + inventory.PROBE],
        env={**os.environ, "PYTHONPATH": str(Path(inventory.__file__).parents[1])},
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    runtime = json.loads(completed.stdout.splitlines()[-1])
    assert runtime["pip_check"] is (pip_status == 0)
    assert runtime["launcher_arguments"]
    if pip_status:
        diagnostic = runtime["pip_check_diagnostics"]
        assert diagnostic["returncode"] == 1
        assert len(diagnostic["stdout_tail"]) <= 4096
        assert "fixture-package requires missing-dependency" in diagnostic["stdout_tail"]
        assert "fixture-private-token" not in json.dumps(diagnostic)
        assert "fixture-private-bearer" not in json.dumps(diagnostic)
    else:
        assert "pip_check_diagnostics" not in runtime
    progress = inventory.probe_progress(completed.stdout)
    assert progress == runtime["probe_progress"]
    assert [(item["stage"], item["status"]) for item in progress] == [
        (stage, status) for stage in inventory.PROBE_STAGES for status in ("started", "completed")
    ]
    assert progress[-1]["elapsed_seconds"] >= progress[0]["elapsed_seconds"]


@pytest.mark.parametrize(
    ("failure", "last_stage"),
    [("artifact", "isaaclab_artifact"), ("arguments", "launcher_arguments")],
)
def test_runtime_child_retains_last_stage_on_actual_exception(failure, last_stage):
    completed = subprocess.run(
        [sys.executable, "-c", probe_fixture(failure) + inventory.PROBE],
        env={**os.environ, "PYTHONPATH": str(Path(inventory.__file__).parents[1])},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode != 0
    assert inventory.probe_progress(completed.stdout)[-1]["stage"] == last_stage
    assert inventory.probe_progress(completed.stdout)[-1]["status"] == "started"


def test_real_child_timeout_keeps_flushed_progress_and_remains_fail_closed(monkeypatch, tmp_path):
    # The real child blocks during the synthetic launcher import. Use a short
    # test budget to prove flushed stdout survives subprocess timeout/kill.
    assert inventory.RUNTIME_PROBE_TIMEOUT_SECONDS == 300
    monkeypatch.setattr(inventory, "RUNTIME_PROBE_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(
        inventory,
        "source_inventory",
        lambda *_: {"profile": inventory.PROFILE, "checks": {}, "issues": []},
    )
    run = subprocess.run

    def execute(argv, **kwargs):
        if argv[0] == "nvidia-smi":
            return SimpleNamespace(stdout="Tesla T4, 595.58.03, 15360 MiB\n")
        assert kwargs["timeout"] == 1
        return run([argv[0], "-c", probe_fixture("timeout") + argv[2]], **kwargs)

    monkeypatch.setattr(inventory.subprocess, "run", execute)
    report = inventory.collect(tmp_path, tmp_path, Path(sys.executable))
    assert not report["ready_for_commissioning"]
    assert report["native_verified"] is False
    diagnostic = report["runtime_error"]
    assert diagnostic["type"] == "TimeoutExpired"
    assert diagnostic["timeout_seconds"] == 1
    assert 1 <= diagnostic["elapsed_seconds"] < 10
    assert diagnostic["progress"][-1]["stage"] == "launcher_import"
    assert diagnostic["progress"][-1]["status"] == "started"
    assert inventory.PROGRESS_PREFIX in diagnostic["stdout_tail"]


def test_timeout_stdout_is_bounded_and_redacted(monkeypatch, tmp_path):
    monkeypatch.setattr(
        inventory,
        "source_inventory",
        lambda *_: {"profile": inventory.PROFILE, "checks": {}, "issues": []},
    )

    def fail(argv, **kwargs):
        if argv[0] == "nvidia-smi":
            return SimpleNamespace(stdout="Tesla T4, 595.58.03, 15360 MiB\n")
        raise subprocess.TimeoutExpired(
            argv, 300, output=b"x" * 6000 + b"\ntoken=fixture-private-token\n"
        )

    monkeypatch.setattr(inventory.subprocess, "run", fail)
    diagnostic = inventory.collect(tmp_path, tmp_path, Path(sys.executable))["runtime_error"]
    assert len(diagnostic["stdout_tail"]) <= 4096
    assert "fixture-private-token" not in diagnostic["stdout_tail"]
    assert diagnostic["progress"] == []
