"""Capacity guards and resource-report failure paths; no AWS or native execution."""

import importlib.util
import json
import signal
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from academy.native_image_probe import capacity_report

ROOT = Path(__file__).resolve().parents[3]


def builder():
    spec = importlib.util.spec_from_file_location("gpu_build", ROOT / "scripts/ec2-gpu-build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def instance():
    return {
        "InstanceType": "g6.2xlarge",
        "VCpuInfo": {"DefaultVCpus": 8},
        "MemoryInfo": {"SizeInMiB": 32768},
        "ProcessorInfo": {"SupportedArchitectures": ["x86_64"]},
        "GpuInfo": {"Gpus": [{"Name": "L4", "Count": 1, "MemoryInfo": {"SizeInMiB": 22888}}]},
    }


@pytest.mark.parametrize("bad", ["ram", "cpu", "fractional", "vram", "gpu", "arch", "type"])
def test_capacity_rejects_lower_or_unreviewed_hardware(bad):
    row = instance()
    if bad == "ram":
        row["MemoryInfo"]["SizeInMiB"] = 16384
    elif bad == "cpu":
        row["VCpuInfo"]["DefaultVCpus"] = 4
    elif bad == "fractional":
        row["GpuInfo"]["Gpus"][0]["Count"] = 0.25
    elif bad == "vram":
        row["GpuInfo"]["Gpus"][0]["MemoryInfo"]["SizeInMiB"] = 16000
    elif bad == "gpu":
        row["GpuInfo"]["Gpus"][0]["Name"] = "A10G"
    elif bad == "arch":
        row["ProcessorInfo"]["SupportedArchitectures"] = ["arm64"]
    else:
        row["InstanceType"] = "g6f.2xlarge"
    with pytest.raises(ValueError, match="Build requires"):
        builder().validate_instance(row)


@pytest.mark.parametrize(
    "quota,active,passes", [(8, False, True), (0, False, False), (8, True, False)]
)
def test_build_capacity_preflight_uses_frozen_identity_and_blocks_overlap(quota, active, passes):
    calls = []

    def client(name, **kwargs):
        calls.append((name, kwargs))
        if name == "service-quotas":
            return SimpleNamespace(get_service_quota=lambda **kw: {"Quota": {"Value": quota}})
        return SimpleNamespace(
            describe_instance_types=lambda **kw: {"InstanceTypes": [instance()]},
            get_paginator=lambda name: SimpleNamespace(
                paginate=lambda **kw: iter(
                    [
                        {"Reservations": []},
                        {
                            "Reservations": [
                                {"Instances": [{"InstanceId": "synthetic"}] if active else []}
                            ]
                        },
                    ]
                )
            ),
        )

    env = {
        "AWS_ACCESS_KEY_ID": "fixture",
        "AWS_SECRET_ACCESS_KEY": "fixture",
        "AWS_SESSION_TOKEN": "fixture",
    }
    config = {"region": "ca-central-1", "build_instance_type": "g6.2xlarge"}
    if passes:
        assert (
            builder().capacity_preflight(SimpleNamespace(client=client), env, config)[
                "applied_g_vcpu_quota"
            ]
            == 8
        )
    else:
        with pytest.raises(ValueError):
            builder().capacity_preflight(SimpleNamespace(client=client), env, config)
    assert all(
        kwargs["aws_access_key_id"] == "fixture" and kwargs["verify"] is True for _, kwargs in calls
    )
    assert calls[0][1]["endpoint_url"] == "https://ec2.ca-central-1.amazonaws.com"
    assert calls[1][1]["endpoint_url"] == "https://servicequotas.ca-central-1.amazonaws.com"


def test_build_timeout_interrupts_packer_then_allows_cleanup(monkeypatch):
    module = builder()
    waits = []
    signals = []

    def wait(timeout=None):
        waits.append(timeout)
        if len(waits) == 1:
            raise subprocess.TimeoutExpired("packer", timeout)
        return 1

    monkeypatch.setattr(
        module.subprocess, "Popen", lambda *a, **kw: SimpleNamespace(pid=123, wait=wait)
    )
    monkeypatch.setattr(module.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    with pytest.raises(RuntimeError, match="reconcile"):
        module.run_build(["packer"], {}, 7200)
    assert waits == [7200, 300]
    assert signals == [(123, signal.SIGINT)]


def test_build_timeout_escalation_is_bounded_and_invalid_bounds_do_not_launch(monkeypatch):
    module = builder()
    waits = []
    signals = []

    def wait(timeout=None):
        waits.append(timeout)
        if len(waits) < 4:
            raise subprocess.TimeoutExpired("packer", timeout)
        return -9

    monkeypatch.setattr(
        module.subprocess, "Popen", lambda *a, **kw: SimpleNamespace(pid=123, wait=wait)
    )
    monkeypatch.setattr(module.os, "killpg", lambda pid, sig: signals.append(sig))
    for value in (0, 9001):
        with pytest.raises(ValueError):
            module.run_build(["packer"], {}, value)
    assert not waits
    with pytest.raises(RuntimeError):
        module.run_build(["packer"], {}, 9000)
    assert waits == [9000, 300, 60, None]
    assert signals == [signal.SIGINT, signal.SIGTERM, signal.SIGKILL]


def evidence(root, *, oom=False, gpu=True, timing=True, journal=True, sampler=True):
    (root / "probe-started-at.txt").write_text("2026-10-23T14:00:00Z\n")
    (root / "probe-time.txt").write_text(
        "Maximum resident set size (kbytes): 24000000\n" if timing else ""
    )
    (root / "gpu-memory.csv").write_text(
        "2026/10/23 14:01:00.000, NVIDIA L4, 22888, 1000\n2026/10/23 14:01:01.000, NVIDIA L4, 22888, 12000\n"
        if gpu
        else ""
    )
    (root / "probe-kernel.log").write_text(
        "Out of memory: Killed process 321 (python)\n" if oom else ""
    )
    (root / "kernel-read-status.txt").write_text("0" if journal else "1")
    (root / "gpu-sampler-complete.txt").write_text("1" if sampler else "0")


def test_measured_capacity_keeps_native_qualification_false(tmp_path):
    evidence(tmp_path)
    report = capacity_report(tmp_path, 0, 42, cpu_count=8, mem_total_kib=33000000)
    assert report["capacity_probe_passed"]
    assert report["peak_process_rss_kib"] == 24000000
    assert report["peak_gpu_memory_used_mib"] == 12000
    assert report["elapsed_seconds"] == 42
    assert not report["workflow_verified"] and not report["worker_qualified"]
    assert json.loads((tmp_path / "capacity.json").read_text()) == report


@pytest.mark.parametrize(
    "failure", ["timeout", "oom", "gpu", "timing", "journal", "sampler", "ram", "cpu"]
)
def test_probe_failure_preserves_evidence_and_never_passes(tmp_path, failure):
    evidence(
        tmp_path,
        oom=failure == "oom",
        gpu=failure != "gpu",
        timing=failure != "timing",
        journal=failure != "journal",
        sampler=failure != "sampler",
    )
    report = capacity_report(
        tmp_path,
        124 if failure == "timeout" else 0,
        1800,
        cpu_count=4 if failure == "cpu" else 8,
        mem_total_kib=16000000 if failure == "ram" else 33000000,
    )
    assert not report["capacity_probe_passed"]
    assert (tmp_path / "capacity.json").is_file()
    if failure == "timeout":
        assert report["timeout_or_kill"]
    if failure == "oom":
        assert report["kernel_oom_events"]
