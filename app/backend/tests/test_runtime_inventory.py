"""Host preflight logic with synthetic process metadata; no real GPU imports."""

import json
from copy import deepcopy
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
