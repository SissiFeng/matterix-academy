"""GPU readiness gating and pre-scene launch failure; synthetic, not GPU acceptance."""

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import academy.native_supervisor as supervisor
import httpx
import pytest
from academy.gateway import GatewayUnavailable, NativeLaunchFailed, RemoteOperationPending
from academy.gpu_health import gpu_issue
from academy.gpu_lifecycle import READINESS
from academy.native_files import SCENE_STARTED, read_json, write_json
from academy.native_runner import NativeFlexRunner
from academy.runs import LAUNCH_FAILED_REASON, WORKERS, SubmitRun
from academy.worker import Journal, Worker
from academy.worker_api import create_worker_app
from fastapi.testclient import TestClient
from test_worker import FixtureRunner, worker_system  # noqa: F401

ROOT = Path(__file__).resolve().parents[3]


def devices(tmp_path, names=("nvidiactl", "nvidia0", "nvidia-uvm")):
    dev = tmp_path / "dev"
    dev.mkdir()
    for name in names:
        (dev / name).touch()
    return dev


def smi(stdout="NVIDIA L4, 595.58.03\n", returncode=0):
    return lambda *args, **kwargs: SimpleNamespace(stdout=stdout, returncode=returncode)


def test_ready_gpu_reports_no_issue(tmp_path):
    assert gpu_issue("595.58.03", dev=devices(tmp_path), run=smi()) is None


@pytest.mark.parametrize(
    ("names", "run", "expected", "message"),
    [
        (("nvidiactl", "nvidia0"), smi(), "595.58.03", "nvidia-uvm is missing"),
        (("nvidiactl", "nvidia0", "nvidia-uvm"), smi("", 9), None, "cannot reach"),
        (("nvidiactl", "nvidia0", "nvidia-uvm"), smi(), "580.1.2", "differs from pinned"),
    ],
)
def test_unready_gpu_explains_why(tmp_path, names, run, expected, message):
    assert message in gpu_issue(expected, dev=devices(tmp_path, names), run=run)


def test_unrunnable_nvidia_smi_is_not_ready(tmp_path):
    def missing(*args, **kwargs):
        raise subprocess.TimeoutExpired("nvidia-smi", 15)

    assert "could not be run" in gpu_issue(None, dev=devices(tmp_path), run=missing)


class LaunchFailingRunner(FixtureRunner):
    """Isaac starts asynchronously, then the supervisor proves it never built a scene."""

    def __init__(self, issue=None):
        super().__init__()
        self.issue = issue

    def readiness_issue(self):
        return self.issue

    def start(self, local):
        self.starts += 1
        raise RemoteOperationPending("Isaac is starting")

    def poll(self, local):
        self.polls += 1
        raise NativeLaunchFailed(
            {
                "native_session_id": local["binding"]["native_session_id"],
                "stage": "launch",
                "reason": "Isaac exited without verified cleanup",
            }
        )


def test_unready_gpu_never_claims_and_the_run_stays_queued(worker_system):  # noqa: F811
    service, submitted, client, path, now = worker_system
    runner = LaunchFailingRunner("GPU device /dev/nvidia0 is missing")
    journal = Journal(path)
    try:
        assert Worker(client, runner, journal, clock=lambda: now).step() is False
        assert service.raw(submitted["run_id"])["status"] == "queued"
        assert journal.read() is None and runner.allocations == 0
    finally:
        journal.close()


def run_to_launch_failure(service, client, path, now, runner):
    journal = Journal(path)
    engine = Worker(client, runner, journal, clock=lambda: now)
    try:
        engine.step()  # claim, bind, launch intent
        engine.step()  # poll observes the launch receipt
        return journal.read()
    finally:
        journal.close()


def resubmit(service, run):
    session = service.store.get(run["owner"], "session#" + run["session_id"])
    return service.submit(
        run["owner"],
        SubmitRun(run_id=uuid4(), session_id=session["id"], expected_version=session["version"]),
    )


def test_pre_scene_launch_failure_fails_cleanly_and_keeps_the_worker(worker_system):  # noqa: F811
    service, submitted, client, path, now = worker_system
    runner = LaunchFailingRunner()
    assert run_to_launch_failure(service, client, path, now, runner) is None
    run = service.raw(submitted["run_id"])
    assert run["status"] == "failed" and run["reason"] == LAUNCH_FAILED_REASON
    assert run["cleanup"]["reset_verified"] and run["cleanup"]["never_started"]
    assert run["cleanup"]["launch_failed"]["stage"] == "launch"
    worker = service.store.get(WORKERS, run["worker_id"])
    assert worker["state"] == "ready" and worker["active_run"] is None
    assert worker["launch_failures"] == 1
    assert runner.starts == 1
    # The learner's session lock is released, so the same design can run again.
    assert resubmit(service, run)["status"] == "queued"


def test_repeated_launch_failures_stop_claims_until_an_operator_acts(worker_system):  # noqa: F811
    service, submitted, client, path, now = worker_system
    run_to_launch_failure(service, client, path, now, LaunchFailingRunner())
    second = resubmit(service, service.raw(submitted["run_id"]))
    run_to_launch_failure(service, client, path, now, LaunchFailingRunner())
    worker = service.store.get(WORKERS, service.raw(second["run_id"])["worker_id"])
    assert worker["launch_failures"] == 2 and worker["state"] == "quarantined"
    third = resubmit(service, service.raw(second["run_id"]))
    assert service.claim(worker["worker_id"]) is None
    assert service.raw(third["run_id"])["status"] == "queued"


def test_verified_run_resets_the_launch_failure_count(worker_system):  # noqa: F811
    service, submitted, client, path, now = worker_system
    run_to_launch_failure(service, client, path, now, LaunchFailingRunner())
    second = resubmit(service, service.raw(submitted["run_id"]))
    journal = Journal(path)
    try:
        engine = Worker(client, FixtureRunner(), journal, clock=lambda: now)
        engine.step()
        if journal.read():
            engine.step()
    finally:
        journal.close()
    run = service.raw(second["run_id"])
    assert run["status"] == "completed"
    assert service.store.get(WORKERS, run["worker_id"])["launch_failures"] == 0


def test_a_run_with_native_reports_cannot_be_closed_as_never_started(worker_system):  # noqa: F811
    service, submitted, client, path, now = worker_system
    journal = Journal(path)
    try:
        engine = Worker(client, FixtureRunner(), journal, clock=lambda: now)
        local = None
        original_save = journal.save

        def stop_after_report(record):
            nonlocal local
            original_save(record)
            if record.get("phase") == "polling":
                local = record
                raise InterruptedError("Synthetic crash after the first native report")

        journal.save = stop_after_report
        with pytest.raises(InterruptedError):
            engine.step()
        run = client.post(local["run"], "snapshots", snapshot=local["last_snapshot"])
        assert run["snapshot"]
        response = client.http.post(
            f"internal/runs/{run['run_id']}/launch-failed",
            json={
                "claim_token": run["claim_token"],
                "native_session_id": local["binding"]["native_session_id"],
                "stage": "launch",
                "reason": "Synthetic",
            },
        )
        assert response.status_code == 409
        assert service.raw(submitted["run_id"]).get("cleanup") is None
    finally:
        journal.close()


def native_runner(tmp_path):
    runner = NativeFlexRunner.__new__(NativeFlexRunner)
    runner.config = SimpleNamespace(run_root=str(tmp_path), driver_version=None)
    run_id = str(uuid4())
    native = str(uuid4())
    folder = tmp_path / run_id
    folder.mkdir()
    (folder / "launch-intent").touch()
    local = {"run": {"run_id": run_id}, "binding": {"native_session_id": native}}
    return runner, local, folder


def test_runner_surfaces_only_a_receipt_for_its_own_session(tmp_path):
    runner, local, folder = native_runner(tmp_path)
    with pytest.raises(RemoteOperationPending):
        runner.poll(local)
    receipt = {"native_session_id": str(uuid4()), "stage": "launch", "reason": "x"}
    write_json(folder / "launch-failed.json", receipt)
    with pytest.raises(GatewayUnavailable):
        runner.poll(local)
    receipt["native_session_id"] = local["binding"]["native_session_id"]
    write_json(folder / "launch-failed.json", receipt)
    with pytest.raises(NativeLaunchFailed) as caught:
        runner.poll(local)
    assert caught.value.receipt == receipt


class FakeChild:
    def __init__(self, exit_code=None):
        self.returncode = exit_code
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def wait(self, timeout=None):
        return self.returncode

    kill = terminate


def supervised(tmp_path, monkeypatch, *, issue=None, simulator_exit=1, scene=False):
    folder = tmp_path / "run"
    folder.mkdir()
    native = str(uuid4())
    write_json(
        folder / "manifest.json",
        {
            "config": {
                "frame_root": str(tmp_path / "frames"),
                "assets_data_dir": str(tmp_path),
                "matterix_root": str(tmp_path),
                "python": sys.executable,
                "display": "",
                "driver_version": "595.58.03",
            },
            "binding": {"native_session_id": native},
            "request": {},
        },
    )
    write_json(folder / "lease.json", {"lease_expires": 4102444800})
    children = [FakeChild(), FakeChild()]

    def popen(args, **kwargs):
        child = children[0] if args[2] == "academy.native_media" else children[1]
        if child is children[1]:
            if scene:
                write_json(folder / SCENE_STARTED, {"native_session_id": native})
            child.returncode = simulator_exit
        return child

    monkeypatch.setattr(supervisor, "runtime_module", lambda request: "native_studio_isaac")
    monkeypatch.setattr(supervisor, "gpu_issue", lambda expected: issue)
    monkeypatch.setattr(supervisor.subprocess, "Popen", popen)
    with pytest.raises(RuntimeError):
        supervisor.supervise(folder)
    return folder, native, children


def test_supervisor_blocks_launch_when_the_gpu_is_unready(tmp_path, monkeypatch):
    folder, native, children = supervised(tmp_path, monkeypatch, issue="driver not loaded")
    receipt = read_json(folder / "launch-failed.json")
    assert receipt == {
        "native_session_id": native,
        "stage": "preflight",
        "reason": "driver not loaded",
        "simulator_exit": None,
    }
    assert not (folder / "fault.json").exists()
    assert not any(child.terminated for child in children)


def test_supervisor_reports_a_pre_scene_simulator_exit_as_never_started(tmp_path, monkeypatch):
    folder, native, children = supervised(tmp_path, monkeypatch)
    receipt = read_json(folder / "launch-failed.json")
    assert receipt["stage"] == "launch" and receipt["simulator_exit"] == 1
    assert children[0].terminated  # media stopped before the receipt was written
    assert not (folder / "fault.json").exists()


def test_supervisor_keeps_post_scene_failures_for_operator_reconciliation(tmp_path, monkeypatch):
    folder, native, children = supervised(tmp_path, monkeypatch, scene=True)
    assert read_json(folder / "fault.json")["native_session_id"] == native
    assert not (folder / "launch-failed.json").exists()


def gpu_ready_script(tmp_path, observed, *, nodes=True):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    dev = tmp_path / "dev"
    dev.mkdir()
    if nodes:
        for name in ("nvidia0", "nvidia-uvm"):
            (dev / name).touch()
    manifest = tmp_path / "image-manifest.json"
    manifest.write_text('{"driver_version": "595.58.03"}')
    log = tmp_path / "log"
    for name, body in {
        "nvidia-modprobe": 'echo "modprobe $*" >> "$LOG"',
        "nvidia-smi": f'case "$*" in *-pm*) echo pm >> "$LOG";; *) printf "{observed}\\n";; esac',
        "sleep": "true",
    }.items():
        (bin_dir / name).write_text("#!/bin/sh\n" + body + "\n")
        (bin_dir / name).chmod(0o755)
    source = (
        (ROOT / "ops/ec2-gpu/academy-gpu-ready.sh")
        .read_text()
        .replace("/etc/academy-native/image-manifest.json", str(manifest))
        .replace("[ -c /dev/", "[ -e " + str(dev) + "/")
    )
    return subprocess.run(
        ["sh", "-c", source],
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "LOG": str(log)},
        capture_output=True,
        text=True,
        timeout=30,
    ), log


def test_boot_unit_loads_uvm_and_verifies_the_pinned_driver(tmp_path):
    result, log = gpu_ready_script(tmp_path, "595.58.03")
    assert result.returncode == 0, result.stderr
    assert "modprobe -u -c=0" in log.read_text()


@pytest.mark.parametrize(("observed", "nodes"), [("580.1.2", True), ("595.58.03", False)])
def test_boot_unit_fails_when_the_driver_never_becomes_ready(tmp_path, observed, nodes):
    result, _ = gpu_ready_script(tmp_path, observed, nodes=nodes)
    assert result.returncode == 1
    assert "NVIDIA driver not ready" in result.stderr


def test_worker_service_cannot_start_without_the_root_gpu_unit():
    unit = (ROOT / "ops/ec2-gpu/academy-native.service").read_text()
    assert "Requires=academy-gpu-ready.service" in unit
    assert "academy-gpu-ready.service" in unit.split("After=", 1)[1].splitlines()[0]
    assert "NoNewPrivileges=true" in unit
    provision = (ROOT / "ops/ec2-gpu/image/provision.sh").read_text()
    assert "systemctl enable academy-gpu-ready.service" in provision
    assert 'apt-mark hold "linux-image-$(uname -r)"' in provision
    finalize = (ROOT / "ops/ec2-gpu/image/finalize.sh").read_text()
    gate = finalize.index("setpriv --no-new-privs")
    assert gate < finalize.index("nvidia-smi")  # before any root GPU access


def readiness_record(service):
    return service.store.get(READINESS, service.store.partition(WORKERS)[0]["worker_id"])


def test_unready_worker_reports_why_and_clears_once_ready(worker_system):  # noqa: F811
    service, submitted, client, path, now = worker_system
    clock = [now]
    runner = LaunchFailingRunner("GPU device /dev/nvidia0 is missing")
    journal = Journal(path)
    try:
        engine = Worker(client, runner, journal, clock=lambda: clock[0])
        assert engine.step() is False
        first = readiness_record(service)
        assert first["issue"] == "GPU device /dev/nvidia0 is missing"
        assert first["at"] == now and first["since"] == now
        engine.step()  # Same issue within 30 s: no new report.
        assert readiness_record(service)["version"] == first["version"]
        clock[0] += 31
        engine.step()  # Persisting issue is refreshed and keeps its original start.
        assert readiness_record(service)["version"] == first["version"] + 1
        assert readiness_record(service)["since"] == now
        runner.issue = None
        engine.ready()
        cleared = readiness_record(service)
        assert cleared["issue"] is None
        engine.ready()
        assert readiness_record(service)["version"] == cleared["version"]
    finally:
        journal.close()


def test_healthy_worker_never_posts_readiness(worker_system):  # noqa: F811
    service, submitted, client, path, now = worker_system
    journal = Journal(path)
    try:
        Worker(client, FixtureRunner(), journal, clock=lambda: now).ready()
        assert service.store.partition(READINESS) == []
    finally:
        journal.close()


def test_failed_readiness_report_never_blocks_the_worker(tmp_path):
    client = Mock()
    client.request.side_effect = httpx.ConnectError("offline")
    journal = Journal(tmp_path / "worker.sqlite")
    try:
        engine = Worker(client, LaunchFailingRunner("driver not loaded"), journal)
        assert engine.ready() is False
        assert engine.ready() is False
        assert client.request.call_count == 2  # Undelivered reports retry next step.
    finally:
        journal.close()


def test_readiness_route_requires_a_machine_credential(store):
    app = TestClient(create_worker_app(store, enabled=True))
    response = app.post("/internal/workers/readiness", json={"issue": "x"})
    assert response.status_code in {401, 403}
    assert store.partition(READINESS) == []
