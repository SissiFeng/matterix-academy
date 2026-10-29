"""Power controller contracts only; fake EC2/SSM are not GPU acceptance."""

from unittest.mock import Mock
from uuid import uuid4

import pytest
from academy.gpu_lifecycle import KEY, PARTITION, GpuLifecycle
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


def test_unknown_run_prevents_shutdown_even_after_a_day(managed):
    gpu, ec2, _, now = managed
    demand(gpu)
    old = gpu.store.get("system#workers", "lab-1")
    gpu.store.put("system#workers", "lab-1", revised(old, active_run="unresolved"), old["version"])
    power(ec2, "running")
    now[0] += 86400
    gpu.reconcile()
    ec2.stop_instances.assert_not_called()
    assert gpu.status()["state"] == "busy"


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
