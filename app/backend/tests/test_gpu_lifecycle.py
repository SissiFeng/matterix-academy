"""Power controller contracts only; fake EC2/SSM are not GPU acceptance."""

from unittest.mock import Mock
from uuid import uuid4

import pytest
from academy.gpu_lifecycle import (
    KEY,
    PARTITION,
    READINESS,
    GpuLifecycle,
    configured,
    startup_seconds,
)
from academy.runs import RunService, SubmitRun, revised
from botocore.exceptions import ClientError, ReadTimeoutError
from fastapi import HTTPException
from test_dispatch import saved, worker


@pytest.fixture
def managed(store):
    now = [10000.0]
    ec2, ssm = Mock(), Mock()
    ec2.describe_instances.return_value = {
        "Reservations": [{"Instances": [{"State": {"Name": "stopped"}}]}]
    }
    ssm.send_command.return_value = {"Command": {"CommandId": "command-1"}}
    ssm.get_command_invocation.return_value = {"Status": "Success"}
    gpu = GpuLifecycle(
        store, "i-pinned", "lab-1", "fixed-document", ec2=ec2, ssm=ssm, clock=lambda: now[0]
    )
    worker(store, last_seen=now[0])
    return gpu, ec2, ssm, now


def demand(gpu):
    gpu.store.transact([gpu.demand_write()])


def power(ec2, state):
    ec2.describe_instances.return_value["Reservations"][0]["Instances"][0]["State"]["Name"] = state


def heartbeat(gpu, now):
    old = gpu.store.get("system#workers", "lab-1")
    gpu.store.put("system#workers", "lab-1", revised(old, last_seen=now[0]), old["version"])


def test_simultaneous_demand_wakes_one_pinned_host_and_waits_for_fresh_worker(managed):
    gpu, ec2, ssm, now = managed
    demand(gpu)
    demand(gpu)
    gpu.reconcile()
    gpu.reconcile()
    ec2.start_instances.assert_called_once_with(InstanceIds=["i-pinned"])
    power(ec2, "running")
    now[0] += 61
    gpu.reconcile()
    assert gpu.status()["state"] == "preparing"
    ssm.send_command.assert_called_once_with(
        InstanceIds=["i-pinned"],
        DocumentName="fixed-document",
        TimeoutSeconds=120,
        Comment="Academy digital twin wakeup",
    )
    now[0] += 61
    heartbeat(gpu, now)
    gpu.reconcile()
    assert gpu.status()["state"] == "ready"


def test_capacity_error_is_durable_and_rate_limited_not_a_failed_native_run(managed):
    gpu, ec2, _, now = managed
    demand(gpu)
    ec2.start_instances.side_effect = ClientError(
        {"Error": {"Code": "InsufficientInstanceCapacity"}}, "StartInstances"
    )
    gpu.reconcile()
    assert gpu.status()["state"] == "capacity_wait"
    for _ in range(5):
        gpu.reconcile()
    assert ec2.start_instances.call_count == 1
    now[0] += 61
    ec2.start_instances.side_effect = None
    power(ec2, "pending")  # Another start's lost response reconciles as pending.
    gpu.reconcile()
    assert ec2.start_instances.call_count == 1
    assert gpu.status()["state"] == "starting"


def test_lost_ssm_response_is_not_replayed(managed):
    gpu, ec2, ssm, now = managed
    demand(gpu)
    power(ec2, "running")
    now[0] += 61
    ssm.send_command.side_effect = ReadTimeoutError(endpoint_url="https://ssm.invalid")
    gpu.reconcile()
    now[0] += 301
    gpu.reconcile()
    assert ssm.send_command.call_count == 1
    assert gpu.status()["state"] == "error"


def test_ssm_not_online_retries_only_definitively_rejected_command(managed):
    gpu, ec2, ssm, now = managed
    demand(gpu)
    power(ec2, "running")
    now[0] += 61
    ssm.send_command.side_effect = ClientError(
        {"Error": {"Code": "InvalidInstanceId"}}, "SendCommand"
    )
    gpu.reconcile()
    now[0] += 61
    ssm.send_command.side_effect = None
    gpu.reconcile()
    assert ssm.send_command.call_count == 2
    assert gpu.status()["state"] == "preparing"
    # Definitive retry must not keep extending the initial worker-start bound.
    now[0] += 601
    gpu.reconcile()
    assert ssm.send_command.call_count == 2
    assert gpu.status()["state"] == "error"


def test_idle_shutdown_requires_one_hour_no_active_run_and_fresh_journal_empty_worker(managed):
    gpu, ec2, _, now = managed
    demand(gpu)
    power(ec2, "running")
    gpu.reconcile()
    now[0] += 3601
    gpu.reconcile()
    ec2.stop_instances.assert_not_called()  # Stale worker is not cleanup proof.
    now[0] += 61
    heartbeat(gpu, now)
    gpu.reconcile()
    ec2.stop_instances.assert_called_once_with(InstanceIds=["i-pinned"])
    assert gpu.status()["state"] == "stopping"


def hold(gpu, run_id, **run):
    if run:
        gpu.store.put("system#runs", run_id, {"version": 1, "run_id": run_id, **run}, None)
    old = gpu.store.get("system#workers", "lab-1")
    gpu.store.put("system#workers", "lab-1", revised(old, active_run=run_id), old["version"])


def test_live_or_unresolvable_run_prevents_shutdown_even_after_a_day(managed):
    gpu, ec2, _, now = managed
    demand(gpu)
    hold(gpu, "unresolved")
    power(ec2, "running")
    now[0] += 86400
    gpu.reconcile()
    ec2.stop_instances.assert_not_called()
    assert gpu.status()["state"] == "busy"


def test_unknown_outcome_holds_the_host_for_one_inspection_window(managed):
    gpu, ec2, _, now = managed
    demand(gpu)
    power(ec2, "running")
    gpu.reconcile()
    hold(gpu, "quarantined", status="outcome_unknown", updated_at=now[0])
    # The quarantined worker keeps its journal and stops claiming, so it goes stale.
    now[0] += 1800
    gpu.reconcile()
    ec2.stop_instances.assert_not_called()
    assert gpu.status()["state"] == "busy"
    now[0] += 1801
    gpu.reconcile()
    ec2.stop_instances.assert_called_once_with(InstanceIds=["i-pinned"])
    # Stopped and no longer wanted: the unresolved run never powers the GPU again.
    power(ec2, "stopped")
    now[0] += 120
    gpu.reconcile()
    ec2.start_instances.assert_not_called()
    assert gpu.status()["state"] == "sleeping"


def test_new_workflow_during_shutdown_is_queued_and_cannot_claim_until_restarted(managed):
    gpu, ec2, _, now = managed
    service = RunService(gpu.store, enabled=True, gpu=gpu, clock=lambda: now[0])
    session = saved(gpu.store)
    demand(gpu)
    old = gpu.record()
    gpu.store.put(
        PARTITION, KEY, {**old, "version": old["version"] + 1, "state": "stopping"}, old["version"]
    )
    request = SubmitRun(
        run_id=uuid4(), session_id=session["id"], expected_version=session["version"]
    )
    result = service.submit("alice", request)
    assert result["status"] == "queued"
    assert service.claim("lab-1") is None
    gpu.reconcile()
    ec2.start_instances.assert_called_once()


def test_invalid_unauthorized_or_stale_submission_does_not_create_gpu_demand(managed):
    gpu, _, _, now = managed
    session = saved(gpu.store)
    request = SubmitRun(
        run_id=uuid4(), session_id=session["id"], expected_version=session["version"]
    )
    service = RunService(gpu.store, gpu=gpu, clock=lambda: now[0])
    with pytest.raises(HTTPException):
        service.submit("alice", request)
    assert gpu.record() is None
    service.enabled = True
    with pytest.raises(HTTPException):
        service.submit("bob", request)
    assert gpu.record() is None


def test_queue_deadline_releases_only_never_claimed_jobs(managed):
    gpu, ec2, _, now = managed
    service = RunService(gpu.store, enabled=True, gpu=gpu, clock=lambda: now[0])
    session = saved(gpu.store)
    request = SubmitRun(
        run_id=uuid4(), session_id=session["id"], expected_version=session["version"]
    )
    service.submit("alice", request)
    now[0] += 3601
    assert service.reap() == 1
    result = service.get("alice", request.run_id)
    assert result["status"] == "failed"
    assert result["cleanup"] == {"reset_verified": True, "never_started": True}
    gpu.reconcile()
    ec2.start_instances.assert_not_called()


def test_demand_committed_during_start_is_preserved(managed):
    gpu, ec2, _, now = managed
    demand(gpu)

    def concurrent_request(**kwargs):
        now[0] += 100
        demand(gpu)

    ec2.start_instances.side_effect = concurrent_request
    gpu.reconcile()
    assert gpu.record()["desired_until"] == now[0] + 3600
    assert gpu.record()["operation_until"] == 0


def test_stop_lock_blocks_claim_and_new_demand_during_stop_is_retained(managed):
    gpu, ec2, _, now = managed
    demand(gpu)
    power(ec2, "running")
    now[0] += 3601
    heartbeat(gpu, now)

    def concurrent_request(**kwargs):
        assert gpu.claim_writes() is None
        demand(gpu)

    ec2.stop_instances.side_effect = concurrent_request
    gpu.reconcile()
    assert gpu.record()["desired_until"] == now[0] + 3600
    assert gpu.claim_writes() is None


def test_expired_queue_cannot_claim_between_reaper_ticks(managed):
    gpu, _, _, now = managed
    service = RunService(gpu.store, enabled=True, gpu=gpu, clock=lambda: now[0])
    session = saved(gpu.store)
    request = SubmitRun(
        run_id=uuid4(), session_id=session["id"], expected_version=session["version"]
    )
    service.submit("alice", request)
    now[0] += 3600
    assert service.claim("lab-1") is None
    assert service.reap() == 1


def test_successful_ssm_without_worker_heartbeat_has_bounded_preparation(managed):
    gpu, ec2, _, now = managed
    demand(gpu)
    power(ec2, "running")
    now[0] += 61
    gpu.reconcile()
    now[0] += 601
    gpu.reconcile()
    assert gpu.status()["state"] == "error"
    ec2.stop_instances.assert_not_called()


def test_power_fence_exceeds_all_callers_hard_lifetimes():
    import re
    from pathlib import Path

    from academy.gpu_lifecycle import OPERATION_SECONDS

    root = Path(__file__).resolve().parents[3]
    configuration = (root / "platform/main.tf").read_text() + (
        root / "platform/workers.tf"
    ).read_text()
    assert OPERATION_SECONDS > max(
        int(x) for x in re.findall(r"timeout\s*=\s*(\d+)", configuration)
    )


def test_delayed_idle_reaper_cannot_lose_fence_while_original_lambda_can_live(managed):
    gpu, ec2, _, now = managed
    demand(gpu)
    power(ec2, "running")
    now[0] += 3601
    heartbeat(gpu, now)

    def delayed_stop(**kwargs):
        # Old 25s lease could be replaced while a 30s reaper was still alive.
        now[0] += 31
        demand(gpu)
        assert gpu.claim_writes() is None
        gpu.reconcile()

    ec2.stop_instances.side_effect = delayed_stop
    gpu.reconcile()
    ec2.stop_instances.assert_called_once()
    assert gpu.claim_writes() is None


def test_superseded_controller_rechecks_token_before_power_mutation(managed):
    gpu, ec2, _, now = managed
    demand(gpu)
    power(ec2, "running")
    now[0] += 3601
    heartbeat(gpu, now)

    def replace_controller(**kwargs):
        old = gpu.record()
        gpu.store.put(
            PARTITION,
            KEY,
            {
                **old,
                "version": old["version"] + 1,
                "operation": "new-controller",
                "operation_until": now[0] + 90,
            },
            old["version"],
        )
        return {"Reservations": [{"Instances": [{"State": {"Name": "running"}}]}]}

    ec2.describe_instances.side_effect = replace_controller
    gpu.reconcile()
    ec2.stop_instances.assert_not_called()


def test_unknown_stop_fences_claims_despite_running_observation_and_fresh_worker(managed):
    gpu, ec2, _, now = managed
    demand(gpu)
    power(ec2, "running")
    now[0] += 3601
    heartbeat(gpu, now)
    ec2.stop_instances.side_effect = ReadTimeoutError(endpoint_url="https://ec2.invalid")
    gpu.reconcile()
    assert gpu.record()["stop_requested"] is True
    now[0] += 61
    demand(gpu)
    heartbeat(gpu, now)
    gpu.reconcile()
    assert gpu.status()["state"] == "error"
    assert gpu.claim_writes() is None
    now[0] += 61
    power(ec2, "stopped")
    gpu.reconcile()
    ec2.start_instances.assert_called_once()
    assert gpu.record()["stop_requested"] is False


def test_unknown_start_clears_old_boot_metadata_before_reconciling_running(managed):
    gpu, ec2, ssm, now = managed
    demand(gpu)
    old = gpu.record()
    gpu.store.put(
        PARTITION,
        KEY,
        {
            **old,
            "version": old["version"] + 1,
            "service_requested": True,
            "command_id": "previous-boot",
            "startup_deadline": now[0] - 1,
        },
        old["version"],
    )
    ec2.start_instances.side_effect = ReadTimeoutError(endpoint_url="https://ec2.invalid")
    gpu.reconcile()
    assert gpu.record()["command_id"] is None
    assert gpu.record()["startup_deadline"] == now[0] + 600
    now[0] += 61
    power(ec2, "running")
    gpu.reconcile()
    ec2.start_instances.assert_called_once()
    ssm.send_command.assert_called_once()
    assert gpu.status()["state"] == "preparing"


def test_clients_target_configured_gpu_region(store, monkeypatch):
    monkeypatch.setenv("ACADEMY_GPU_INSTANCE_ID", "i-pinned")
    monkeypatch.setenv("ACADEMY_GPU_WORKER_ID", "lab-1")
    monkeypatch.setenv("ACADEMY_GPU_START_DOCUMENT", "fixed-document")
    monkeypatch.setenv("ACADEMY_GPU_REGION", "us-east-2")
    created = []
    monkeypatch.setattr(
        "academy.gpu_lifecycle.boto3.client",
        lambda name, **kwargs: created.append((name, kwargs["region_name"])) or Mock(),
    )
    gpu = configured(store)
    gpu.client("ec2")
    gpu.client("ssm")
    assert created == [("ec2", "us-east-2"), ("ssm", "us-east-2")]
    monkeypatch.delenv("ACADEMY_GPU_REGION")
    assert configured(store).region is None  # boto3 falls back to the Lambda's own region


def test_capacity_request_works_before_execution_qualification_and_is_idempotent(managed):
    from academy.runs import GpuRequest

    gpu, ec2, _, now = managed
    service = RunService(gpu.store, enabled=False, gpu=gpu, clock=lambda: now[0])
    session = saved(gpu.store)
    request = GpuRequest(request_id=uuid4(), expected_version=session["version"])
    result = service.request_gpu("alice", session["id"], request)
    assert result["active"]
    assert result["request"]["request_id"] == str(request.request_id)
    assert gpu.store.partition("system#queue") == []
    assert gpu.store.partition("system#runs") == []
    assert gpu.store.get("alice", "session#" + session["id"]) == session
    original = gpu.record()
    now[0] += 20
    assert service.request_gpu("alice", session["id"], request)["request"] == result["request"]
    service.request_gpu(
        "alice", session["id"], GpuRequest(request_id=uuid4(), expected_version=session["version"])
    )
    assert gpu.record() == original
    gpu.reconcile()
    ec2.start_instances.assert_called_once_with(InstanceIds=["i-pinned"])
    with pytest.raises(HTTPException) as blocked:
        service.submit(
            "alice",
            SubmitRun(
                run_id=uuid4(), session_id=session["id"], expected_version=session["version"]
            ),
        )
    assert blocked.value.status_code == 503


def test_capacity_request_rejects_other_owner_stale_or_unconfigured_without_demand(managed):
    from academy.runs import GpuRequest
    from academy.store import Conflict

    gpu, _, _, now = managed
    service = RunService(gpu.store, gpu=gpu, clock=lambda: now[0])
    session = saved(gpu.store)
    request = GpuRequest(request_id=uuid4(), expected_version=session["version"])
    with pytest.raises(HTTPException) as denied:
        service.request_gpu("mallory", session["id"], request)
    assert denied.value.status_code == 404
    with pytest.raises(Conflict):
        service.request_gpu(
            "alice", session["id"], GpuRequest(request_id=uuid4(), expected_version=99)
        )
    with pytest.raises(HTTPException) as missing:
        RunService(gpu.store).request_gpu("alice", session["id"], request)
    assert missing.value.status_code == 503
    assert gpu.record() is None
    assert service.gpu_request_status("alice", session["id"])["request"] is None


def test_expired_capacity_request_requires_new_id_and_concurrent_edit_rolls_back(
    managed, monkeypatch
):
    from academy.runs import GpuRequest
    from academy.store import Conflict

    gpu, _, _, now = managed
    service = RunService(gpu.store, gpu=gpu, clock=lambda: now[0])
    session = saved(gpu.store)
    request = GpuRequest(request_id=uuid4(), expected_version=session["version"])
    service.request_gpu("alice", session["id"], request)
    now[0] += 3601
    assert not service.request_gpu("alice", session["id"], request)["active"]
    before = gpu.record()
    original = gpu.store.transact

    def edit_then_transact(writes):
        gpu.store.put("alice", "session#" + session["id"], revised(session), session["version"])
        original(writes)

    monkeypatch.setattr(gpu.store, "transact", edit_then_transact)
    with pytest.raises(Conflict):
        service.request_gpu(
            "alice",
            session["id"],
            GpuRequest(request_id=uuid4(), expected_version=session["version"]),
        )
    assert gpu.record() == before
    assert service.gpu_request_status("alice", session["id"])["request"]["request_id"] == str(
        request.request_id
    )


def test_capacity_routes_are_authenticated_and_return_accepted_receipt(client, app, managed):
    gpu, ec2, _, now = managed
    app.state.runs.gpu = gpu
    app.state.runs.clock = lambda: now[0]
    from test_learning import lesson

    response = client.post("/api/sessions", json=lesson())
    assert response.status_code == 201
    session = response.json()
    path = f"/api/sessions/{session['id']}/gpu-request"
    request = {"request_id": str(uuid4()), "expected_version": session["version"]}
    assert client.get(path).json()["request"] is None
    response = client.post(path, json=request)
    assert response.status_code == 202
    assert response.json()["active"]
    assert response.json()["gpu"]["state"] == "starting"
    assert client.get(path).json()["request"] == response.json()["request"]
    ec2.start_instances.assert_called_once()
    client.cookies.clear()
    assert client.post(path, json=request).status_code == 401
    assert client.get(path).status_code == 401


def test_capacity_request_retries_shared_demand_contention_without_replaying_power(
    managed, monkeypatch
):
    from academy.runs import GpuRequest

    gpu, ec2, _, now = managed
    service = RunService(gpu.store, gpu=gpu, clock=lambda: now[0])
    session = saved(gpu.store)
    original = gpu.store.transact
    raced = False

    def concurrent_demand(writes):
        nonlocal raced
        if not raced:
            raced = True
            original([gpu.demand_write()])
        original(writes)

    monkeypatch.setattr(gpu.store, "transact", concurrent_demand)
    result = service.request_gpu(
        "alice", session["id"], GpuRequest(request_id=uuid4(), expected_version=session["version"])
    )
    assert raced and result["active"]
    assert gpu.store.get("alice", "session#" + session["id"]) == session
    ec2.start_instances.assert_not_called()


def test_capacity_request_id_cannot_be_reused_with_another_saved_version(managed):
    from academy.runs import GpuRequest
    from academy.store import Conflict

    gpu, _, _, now = managed
    service = RunService(gpu.store, gpu=gpu, clock=lambda: now[0])
    session = saved(gpu.store)
    request_id = uuid4()
    service.request_gpu(
        "alice",
        session["id"],
        GpuRequest(request_id=request_id, expected_version=session["version"]),
    )
    changed = revised(session)
    gpu.store.put("alice", "session#" + session["id"], changed, session["version"])
    with pytest.raises(Conflict):
        service.request_gpu(
            "alice",
            session["id"],
            GpuRequest(request_id=request_id, expected_version=changed["version"]),
        )


# Automatic recovery for a host whose worker never connects after a boot.


def silent(gpu):
    """A worker that has never heartbeated, so no boot can count it as connected."""
    old = gpu.store.get("system#workers", "lab-1")
    gpu.store.put("system#workers", "lab-1", revised(old, last_seen=0), old["version"])


def tick(gpu, now, seconds=11):
    now[0] += seconds
    return gpu.reconcile()


def boot(gpu, ec2, ssm, now):
    """Stopped → started → SSM sent; returns once the worker is being prepared."""
    tick(gpu, now)
    power(ec2, "running")
    status = tick(gpu, now, 61)
    assert status["state"] == "preparing"
    return status


def report(gpu, now, issue, since=None):
    old = gpu.store.get(READINESS, "lab-1")
    fields = {"issue": issue, "at": now[0], "since": now[0] if since is None else since}
    gpu.store.put(
        READINESS,
        "lab-1",
        revised(old, **fields) if old else {"version": 1, **fields},
        old["version"] if old else None,
    )


def test_silent_worker_restarts_service_once_then_power_cycles_then_halts(managed):
    gpu, ec2, ssm, now = managed
    silent(gpu)
    demand(gpu)
    boot(gpu, ec2, ssm, now)
    assert ssm.send_command.call_count == 1
    # Startup deadline passes with a finished SSM command: resend the fixed document once.
    status = tick(gpu, now, 601)
    assert status["state"] == "preparing" and "Restarting the worker" in status["message"]
    assert ssm.send_command.call_count == 2
    assert ec2.stop_instances.call_count == 0
    # The shorter second deadline passes too: power-cycle the host.
    status = tick(gpu, now, 301)
    assert status["state"] == "stopping" and "Restarting the GPU host" in status["message"]
    ec2.stop_instances.assert_called_once_with(InstanceIds=["i-pinned"])
    assert gpu.claim_writes() is None  # The stop fence blocks claims.
    power(ec2, "stopped")
    status = tick(gpu, now)
    assert status["state"] == "starting" and ec2.start_instances.call_count == 2
    power(ec2, "running")
    tick(gpu, now)
    assert ssm.send_command.call_count == 3
    # Still silent after the power cycle: stop and stay stopped.
    status = tick(gpu, now, 601)
    assert status["state"] == "error" and "operator" in status["message"]
    assert ec2.stop_instances.call_count == 2
    assert ssm.send_command.call_count == 3
    power(ec2, "stopped")
    for _ in range(3):
        status = tick(gpu, now, 61)
    demand(gpu)  # A new request while halted does not pay for another boot.
    status = tick(gpu, now, 61)
    assert status["state"] == "error" and gpu.record()["error_code"] == "worker_start_failed"
    assert ec2.start_instances.call_count == 2


def test_halt_lapses_with_demand_and_a_later_request_boots_fresh(managed):
    gpu, ec2, ssm, now = managed
    silent(gpu)
    gpu.store.put(
        PARTITION, KEY, {"version": 1, "halted_until": now[0] + 3600, "recovery": 2}, None
    )
    power(ec2, "stopped")
    tick(gpu, now)  # No demand: sleeping resets the ladder.
    assert gpu.record()["recovery"] == 0 and gpu.record()["halted_until"] == 0
    demand(gpu)
    assert tick(gpu, now)["state"] == "starting"


def test_unknown_ssm_outcome_power_cycles_without_replaying_the_command(managed):
    gpu, ec2, ssm, now = managed
    silent(gpu)
    demand(gpu)
    boot(gpu, ec2, ssm, now)
    ssm.get_command_invocation.side_effect = ClientError(
        {"Error": {"Code": "InvocationDoesNotExist"}}, "GetCommandInvocation"
    )
    status = tick(gpu, now, 601)
    assert status["state"] == "stopping"
    assert ssm.send_command.call_count == 1
    ec2.stop_instances.assert_called_once()


def test_lost_send_response_power_cycles_without_replay(managed):
    gpu, ec2, ssm, now = managed
    silent(gpu)
    demand(gpu)
    tick(gpu, now)
    power(ec2, "running")
    ssm.send_command.side_effect = ReadTimeoutError(endpoint_url="https://ssm.invalid")
    tick(gpu, now, 61)
    ssm.send_command.side_effect = None
    for _ in range(3):
        tick(gpu, now, 61)
    assert ssm.send_command.call_count == 1
    status = tick(gpu, now, 601)
    assert status["state"] == "stopping" and ssm.send_command.call_count == 1


def test_unready_gpu_report_is_shown_and_cycles_the_host_early(managed):
    gpu, ec2, ssm, now = managed
    silent(gpu)
    demand(gpu)
    boot(gpu, ec2, ssm, now)
    report(gpu, now, "GPU device /dev/nvidia-uvm is missing")
    status = tick(gpu, now)
    assert status["state"] == "preparing"
    assert status["detail"] == "GPU device /dev/nvidia-uvm is missing"
    assert "GPU is not ready" in status["message"]
    since = now[0] - 11
    now[0] += 110
    report(gpu, now, "GPU device /dev/nvidia-uvm is missing", since=since)
    status = tick(gpu, now)
    # Well before the 600 s deadline; a service restart cannot load a kernel module.
    assert status["state"] == "stopping"
    assert ssm.send_command.call_count == 1
    ec2.stop_instances.assert_called_once()


def test_report_from_before_this_boot_is_ignored(managed):
    gpu, ec2, ssm, now = managed
    silent(gpu)
    report(gpu, now, "driver not loaded", since=0)
    demand(gpu)
    boot(gpu, ec2, ssm, now)
    status = tick(gpu, now, 200)
    assert status["state"] == "preparing" and "detail" not in status
    ec2.stop_instances.assert_not_called()


def test_cleared_unready_report_restores_the_preparing_message(managed):
    gpu, ec2, ssm, now = managed
    silent(gpu)
    demand(gpu)
    boot(gpu, ec2, ssm, now)
    report(gpu, now, "driver not loaded")
    assert "detail" in tick(gpu, now)
    report(gpu, now, None)
    status = tick(gpu, now)
    assert status["state"] == "preparing" and "detail" not in status
    assert status["message"] == "GPU started. Preparing the Isaac worker."


def test_worker_that_connects_after_a_power_cycle_resets_the_ladder(managed):
    gpu, ec2, ssm, now = managed
    silent(gpu)
    demand(gpu)
    boot(gpu, ec2, ssm, now)
    tick(gpu, now, 601)
    tick(gpu, now, 301)
    power(ec2, "stopped")
    tick(gpu, now)
    power(ec2, "running")
    tick(gpu, now)
    now[0] += 30
    heartbeat(gpu, now)
    status = tick(gpu, now, 1)
    assert status["state"] == "ready"
    record = gpu.record()
    assert record["recovery"] == 0 and record["note"] is None


def test_unconfirmed_stop_is_reissued_while_claims_stay_fenced(managed):
    gpu, ec2, ssm, now = managed
    silent(gpu)
    demand(gpu)
    boot(gpu, ec2, ssm, now)
    tick(gpu, now, 601)
    tick(gpu, now, 301)  # power cycle: one stop accepted, EC2 still reports running
    assert ec2.stop_instances.call_count == 1
    assert tick(gpu, now, 60)["state"] == "error"
    assert ec2.stop_instances.call_count == 1
    status = tick(gpu, now, 300)
    assert status["state"] == "stopping" and gpu.record()["error_code"] == "stop_reissued"
    assert ec2.stop_instances.call_count == 2
    assert gpu.claim_writes() is None


def test_capacity_backoff_doubles_to_five_minutes_and_resets_on_start(managed):
    gpu, ec2, _, now = managed
    demand(gpu)
    ec2.start_instances.side_effect = ClientError(
        {"Error": {"Code": "InsufficientInstanceCapacity"}}, "StartInstances"
    )
    waits = []
    gpu.reconcile()
    for _ in range(5):
        record = gpu.record()
        waits.append(record["retry_at"] - now[0])
        now[0] = record["retry_at"]
        status = gpu.reconcile()
    assert waits == [60, 120, 240, 300, 300]
    assert status["state"] == "capacity_wait" and status["attempts"] == 6
    ec2.start_instances.side_effect = None
    now[0] = gpu.record()["retry_at"]
    assert gpu.reconcile()["state"] == "starting"
    assert gpu.record()["capacity_attempts"] == 0


@pytest.mark.parametrize(
    ("value", "expected"), [(None, 600), ("900", 900), ("30", 300), ("9999", 1800), ("x", 600)]
)
def test_startup_bound_is_configurable_within_limits(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("ACADEMY_GPU_STARTUP_SECONDS", raising=False)
    else:
        monkeypatch.setenv("ACADEMY_GPU_STARTUP_SECONDS", value)
    assert startup_seconds() == expected


def test_one_missed_heartbeat_long_after_boot_is_not_an_operator_fault(managed):
    gpu, ec2, _, now = managed
    demand(gpu)
    boot(gpu, ec2, None, now)
    for _ in range(70):  # ready for longer than the startup bound
        now[0] += 10
        heartbeat(gpu, now)
        assert gpu.reconcile()["state"] == "ready"
    now[0] += 50
    assert gpu.reconcile()["state"] == "preparing"
    assert gpu.claim_writes() is not None
    heartbeat(gpu, now)
    assert tick(gpu, now)["state"] == "ready"
    # A worker that stays quiet for the whole bound still needs an operator.
    now[0] += 601
    status = gpu.reconcile()
    assert status["state"] == "error"
    assert gpu.record()["error_code"] == "worker_start_timeout"
    assert gpu.claim_writes() is None


@pytest.mark.parametrize("code", ["RequestLimitExceeded", "Throttling"])
def test_aws_throttling_is_retried_soon_and_is_not_an_operator_fault(managed, code):
    gpu, ec2, _, now = managed
    demand(gpu)
    ec2.describe_instances.side_effect = ClientError({"Error": {"Code": code}}, "DescribeInstances")
    gpu.reconcile()
    assert gpu.status()["state"] == "preparing"
    assert gpu.record()["retry_at"] == now[0] + 30
    ec2.describe_instances.side_effect = None
    now[0] += 31
    assert gpu.reconcile()["state"] == "starting"
    ec2.start_instances.assert_called_once()
