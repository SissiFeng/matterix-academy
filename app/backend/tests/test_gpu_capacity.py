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
CANDIDATES = [("g6.2xlarge", "L4"), ("g5.2xlarge", "A10G"), ("g4dn.2xlarge", "T4")]


def builder():
    spec = importlib.util.spec_from_file_location("gpu_build", ROOT / "scripts/ec2-gpu-build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def instance(instance_type="g6.2xlarge", gpu="L4"):
    return {
        "InstanceType": instance_type,
        "VCpuInfo": {"DefaultVCpus": 8},
        "MemoryInfo": {"SizeInMiB": 32768},
        "ProcessorInfo": {"SupportedArchitectures": ["x86_64"]},
        "GpuInfo": {
            "Gpus": [
                {
                    "Name": gpu,
                    "Count": 1,
                    "GpuPartitionSize": 1.0,
                    "MemoryInfo": {"SizeInMiB": 16384 if gpu == "T4" else 22888},
                }
            ]
        },
    }


@pytest.mark.parametrize("instance_type,gpu", CANDIDATES)
def test_full_rtx_candidates_meet_the_reviewed_commissioning_minimum(instance_type, gpu):
    builder().validate_instance(instance(instance_type, gpu))


@pytest.mark.parametrize("instance_type,gpu", CANDIDATES)
@pytest.mark.parametrize(
    "bad", ["ram", "cpu", "fractional", "partition", "vram", "gpu", "arch", "type"]
)
def test_capacity_rejects_lower_or_unreviewed_hardware(bad, instance_type, gpu):
    row = instance(instance_type, gpu)
    if bad == "ram":
        row["MemoryInfo"]["SizeInMiB"] = 16384
    elif bad == "cpu":
        row["VCpuInfo"]["DefaultVCpus"] = 4
    elif bad == "fractional":
        row["GpuInfo"]["Gpus"][0]["Count"] = 0.25
    elif bad == "partition":
        row["GpuInfo"]["Gpus"][0]["GpuPartitionSize"] = 0.5
    elif bad == "vram":
        row["GpuInfo"]["Gpus"][0]["MemoryInfo"]["SizeInMiB"] = 16383 if gpu == "T4" else 21999
    elif bad == "gpu":
        row["GpuInfo"]["Gpus"][0]["Name"] = "A100"
    elif bad == "arch":
        row["ProcessorInfo"]["SupportedArchitectures"] = ["arm64"]
    else:
        row["InstanceType"] = "g6f.2xlarge"
    with pytest.raises(ValueError, match="Build requires"):
        builder().validate_instance(row)


@pytest.mark.parametrize(
    "instance_type,gpu",
    [
        ("g4dn.2xlarge", "A10G"),
        ("g5.2xlarge", "T4"),
        ("g6.2xlarge", "A10G"),
        ("g6.4xlarge", "T4"),
        ("g6e.2xlarge", "L4"),
    ],
)
def test_instance_family_cannot_claim_a_different_candidate_gpu(instance_type, gpu):
    with pytest.raises(ValueError, match="Build requires"):
        builder().validate_instance(instance(instance_type, gpu))


@pytest.mark.parametrize(
    "quota,active,passes", [(8, False, True), (0, False, False), (8, True, False)]
)
@pytest.mark.parametrize("instance_type,gpu", CANDIDATES)
def test_build_capacity_preflight_uses_frozen_identity_and_blocks_overlap(
    quota, active, passes, instance_type, gpu
):
    calls = []

    def client(name, **kwargs):
        calls.append((name, kwargs))
        if name == "service-quotas":
            return SimpleNamespace(get_service_quota=lambda **kw: {"Quota": {"Value": quota}})
        return SimpleNamespace(
            describe_instance_types=lambda **kw: {"InstanceTypes": [instance(instance_type, gpu)]},
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
    config = {"region": "ca-central-1", "build_instance_type": instance_type}
    if passes:
        report = builder().capacity_preflight(SimpleNamespace(client=client), env, config)
        assert report["applied_g_vcpu_quota"] == 8
        assert report["instance_type"] == instance_type
        assert report["gpu"]["Name"] == gpu
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
    "name,total,passes",
    [
        ("Tesla T4", 15360, True),
        ("NVIDIA T4", 15360, True),
        ("Tesla T4", 15359, False),
        ("NVIDIA A10G", 22888, True),
        ("NVIDIA A10G", 15360, False),
        ("NVIDIA L4", 21999, False),
        ("NVIDIA L40S", 46068, True),
        ("NVIDIA A100", 40000, False),
    ],
)
def test_measured_capacity_enforces_each_reviewed_gpu_memory_floor(tmp_path, name, total, passes):
    evidence(tmp_path)
    (tmp_path / "gpu-memory.csv").write_text(
        f"2026/10/26 14:01:00.000, {name}, {total}, 1000\n"
        f"2026/10/26 14:01:01.000, {name}, {total}, 12000\n"
    )
    report = capacity_report(tmp_path, 0, 42, cpu_count=8, mem_total_kib=33000000)
    assert report["capacity_probe_passed"] is passes
    assert not report["workflow_verified"] and not report["worker_qualified"]


@pytest.mark.parametrize(
    "second",
    [
        "NVIDIA A10G, 22888, 12000",
        "NVIDIA L4, 22889, 12000",
        "NVIDIA L4, 22888, 22889",
        "NVIDIA L4, 22888, -1",
        "NVIDIA L4, N/A, 1000",
        "malformed",
    ],
)
def test_measured_capacity_rejects_inconsistent_or_invalid_gpu_samples(tmp_path, second):
    evidence(tmp_path)
    (tmp_path / "gpu-memory.csv").write_text(
        f"2026/10/26 14:01:00.000, NVIDIA L4, 22888, 1000\n2026/10/26 14:01:01.000, {second}\n"
    )
    report = capacity_report(tmp_path, 0, 42, cpu_count=8, mem_total_kib=33000000)
    assert not report["capacity_probe_passed"]


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
