"""Control-plane fault tests. Native-looking reports are synthetic fixtures only."""

import hashlib
from uuid import uuid4

import pytest
from academy.models import Experiment
from academy.remote_run import RemoteRunRequest
from academy.runs import (
    QUEUE,
    WORKERS,
    BindRequest,
    CleanupRequest,
    LeaseRequest,
    RunControl,
    RunService,
    SnapshotRequest,
    StartRequest,
    SubmitRun,
    UnknownRequest,
    revised,
    worker_credential,
)
from academy.store import Conflict, Write
from academy.teaching import new_session
from academy.worker_api import create_worker_app
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_learning import lesson
from test_remote_run import report

ALL_SLOTS = [f"{row}{col}" for row in "ABCD" for col in (1, 2, 3)]
FIXTURE_CAPABILITY = {
    "slots": {"tips": ALL_SLOTS, "stock": ALL_SLOTS, "plate": ALL_SLOTS, "waste": ["D3"]},
    "wells": ["A1", "A2", "A3"],
    "volume_ul": {"min": 1, "max": 300},
    "max_source_ul": 1500,
    "max_steps": 64,
}


def worker(store, name="lab-1", **changes):
    token = name + "." + "s" * 40
    item = dict(
        version=1,
        worker_id=name,
        credential_version=1,
        token_digest=hashlib.sha256(token.encode()).hexdigest(),
        credential_expires=2000000000,
        revoked=False,
        qualified=True,
        state="ready",
        active_run=None,
        controls=["pause", "resume"],
        engine_version="fixture-engine",
        asset_version="fixture-assets",
        scenes=["flex-first-transfer"],
        capabilities={"flex-first-transfer": FIXTURE_CAPABILITY},
    )
    item.update(changes)
    store.put(WORKERS, name, item, None)
    return token


def saved(store, owner="alice"):
    session = new_session(Experiment.model_validate(lesson()))
    session["learning"] = dict(
        visited=["pipette", "tips", "stock", "plate", "waste"],
        checks=["instrument", "labware", "liquids", "simulation"],
        location_answer="well",
        prediction={"source": 900, "tip": 100, "target": 0},
    )
    store.put(owner, "session#" + session["id"], session, None)
    return session


@pytest.fixture
def system(store):
    clock = [1790863200.0]
    service = RunService(store, enabled=True, clock=lambda: clock[0])
    worker(store)
    session = saved(store)
    request = SubmitRun(
        run_id=uuid4(), session_id=session["id"], expected_version=session["version"]
    )
    service.submit("alice", request)
    return service, clock, request


def start(system):
    service, _, request = system
    run = service.claim("lab-1")
    data = StartRequest(claim_token=run["claim_token"], command_id=uuid4())
    run = service.start("lab-1", request.run_id, data)
    binding = BindRequest(
        claim_token=run["claim_token"],
        native_session_id=uuid4(),
        expected_revision=1,
        engine_version="fixture-engine",
        asset_version="fixture-assets",
    )
    run = service.bind("lab-1", request.run_id, binding)
    return run, data


def snapshot(run, completed=0, sequence=0):
    request = RemoteRunRequest(
        run_id=run["run_id"],
        expected_revision=1,
        experiment=run["plan"],
        plan_hash=run["plan_hash"],
    )
    return SnapshotRequest(
        claim_token=run["claim_token"],
        snapshot=report(run["binding"]["native_session_id"], request, completed, sequence),
    )


def test_atomic_creation_and_idempotent_retry(system):
    service, _, request = system
    first = service.get("alice", request.run_id)
    assert service.submit("alice", request) == first
    assert len(service.store.partition(QUEUE)) == 1
    session = service.store.get("alice", "session#" + str(request.session_id))
    assert session["version"] == request.expected_version + 1
    with pytest.raises(Conflict):
        service.submit("bob", request)
    with pytest.raises(HTTPException) as error:
        service.get("bob", request.run_id)
    assert error.value.status_code == 404
    with pytest.raises(HTTPException):
        service.submit(
            "alice",
            request.model_copy(update={"run_id": uuid4(), "expected_version": session["version"]}),
        )
    assert len(service.store.partition(QUEUE)) == 1


def test_transaction_failure_rolls_back_all_records(store):
    store.put("a", "one", {"version": 1}, None)
    with pytest.raises(Conflict):
        store.transact(
            [Write("a", "two", {"version": 1}, None), Write("a", "one", {"version": 2}, 77)]
        )
    assert store.get("a", "two") is None
    assert store.get("a", "one")["version"] == 1


def test_lost_claim_response_returns_original_grant(system):
    service, _, _ = system
    first = service.claim("lab-1")
    assert service.claim("lab-1") == first
    worker(service.store, "lab-2")
    assert service.claim("lab-2") is None
    assert "owner" not in first and "token_digest" not in first


def test_expired_claim_never_requeues_even_without_snapshot(system):
    service, clock, request = system
    claimed = service.claim("lab-1")
    clock[0] += 61
    with pytest.raises(HTTPException):
        service.start(
            "lab-1",
            request.run_id,
            StartRequest(claim_token=claimed["claim_token"], command_id=uuid4()),
        )
    assert service.reap() == 1
    assert service.raw(request.run_id)["status"] == "outcome_unknown"
    assert service.store.partition(QUEUE) == []
    assert service.worker("lab-1")["state"] == "quarantined"
    worker(service.store, "lab-2")
    assert service.claim("lab-2") is None


def test_start_grant_is_idempotent_but_not_reissued(system):
    service, _, request = system
    run, command = start(system)
    assert service.start("lab-1", request.run_id, command)["start_command_id"] == str(
        command.command_id
    )
    with pytest.raises(HTTPException):
        service.start("lab-1", request.run_id, command.model_copy(update={"command_id": uuid4()}))
    assert run["status"] == "starting"


def test_native_write_and_terminal_ack_replay(system):
    service, clock, request = system
    run, _ = start(system)
    first = snapshot(run, 1, 1)
    service.snapshot("lab-1", request.run_id, first)
    assert service.get("alice", request.run_id)["completed_steps"] == 1
    # Same-sequence changes, forged plan and runtime changes cannot replace progress.
    for payload in [
        first.model_copy(
            update={"snapshot": first.snapshot.model_copy(update={"plan_hash": "0" * 64})}
        ),
        first.model_copy(
            update={"snapshot": first.snapshot.model_copy(update={"engine_version": "different"})}
        ),
        snapshot(run, 0, 0),
    ]:
        with pytest.raises(HTTPException):
            service.snapshot("lab-1", request.run_id, payload)
    final = snapshot(run, 4, 2)
    stored = service.snapshot("lab-1", request.run_id, final)
    with pytest.raises(Conflict):
        service.snapshot("lab-1", request.run_id, snapshot(run, 4, 3))
    clock[0] += 90
    assert service.snapshot("lab-1", request.run_id, final) == stored
    assert service.raw(request.run_id)["status"] == "completed"


def test_machine_scope_and_revocation(system):
    service, _, request = system
    run, _ = start(system)
    worker(service.store, "lab-2")
    with pytest.raises(HTTPException):
        service.snapshot("lab-2", request.run_id, snapshot(run))
    with pytest.raises(HTTPException):
        service.heartbeat("lab-1", request.run_id, LeaseRequest(claim_token="x" * 43))
    old = service.worker("lab-1")
    service.store.put(WORKERS, "lab-1", revised(old, revoked=True), old["version"])
    assert worker_credential(service.store, "Bearer lab-1." + "s" * 40) is None
    with pytest.raises(HTTPException):
        service.snapshot("lab-1", request.run_id, snapshot(run))
    assert service.reap() == 1


def test_controls_are_versioned_and_pause_needs_native_ack(system):
    service, _, request = system
    run, _ = start(system)
    service.snapshot("lab-1", request.run_id, snapshot(run, 0, 1))
    current = service.get("alice", request.run_id)
    command = RunControl(command_id=uuid4(), expected_version=current["version"], action="pause")
    paused_request = service.control("alice", request.run_id, command)
    assert paused_request["status"] == "pause_requested"
    assert service.control("alice", request.run_id, command) == paused_request
    with pytest.raises(Conflict):
        service.control("alice", request.run_id, command.model_copy(update={"action": "cancel"}))
    body = snapshot(run, 0, 2).model_dump(mode="json")
    body["snapshot"]["status"] = "paused"
    body["control_id"] = str(command.command_id)
    service.snapshot("lab-1", request.run_id, SnapshotRequest.model_validate(body))
    assert service.get("alice", request.run_id)["status"] == "paused"


@pytest.mark.parametrize("action", ["pause", "resume"])
@pytest.mark.parametrize("terminal_status", ["completed", "failed"])
def test_control_ack_racing_terminal_snapshot_keeps_terminal_outcome(
    system, action, terminal_status
):
    service, _, request = system
    run, _ = start(system)
    initial = snapshot(run, 0, 1).model_dump(mode="json")
    if action == "resume":
        initial["snapshot"]["status"] = "paused"
    current = service.snapshot("lab-1", request.run_id, SnapshotRequest.model_validate(initial))
    command = RunControl(command_id=uuid4(), expected_version=current["version"], action=action)
    service.control("alice", request.run_id, command)
    body = snapshot(run, 4 if terminal_status == "completed" else 0, 2).model_dump(mode="json")
    body["snapshot"]["status"] = terminal_status
    if terminal_status == "failed":
        body["snapshot"]["error"] = "Synthetic terminal failure"
    body["control_id"] = str(command.command_id)
    response = service.snapshot("lab-1", request.run_id, SnapshotRequest.model_validate(body))
    assert response["status"] == terminal_status
    assert response["control"]["acknowledged"] is True
    assert (
        service.snapshot("lab-1", request.run_id, SnapshotRequest.model_validate(body)) == response
    )
    assert service.cleanup("lab-1", request.run_id, cleanup(run))["cleanup"]["reset_verified"]


def test_transaction_update_preserves_session_creation_order(store):
    for index in range(51):
        session = {"version": 1, "id": str(index), "created_at": f"2026-10-01T00:00:{index:02d}Z"}
        store.put("alice", f"session#{index}", session, None)
    before = [session["id"] for session in store.list("alice")]
    oldest = store.get("alice", "session#0")
    store.transact([Write("alice", "session#0", revised(oldest, remote_active_run="fixture"), 1)])
    assert [session["id"] for session in store.list("alice")] == before
    assert "0" not in before
    assert store.get("alice", "session#0")["version"] == 2


def test_queued_cancel_releases_session_without_touching_sim(system):
    service, _, request = system
    result = service.control(
        "alice", request.run_id, RunControl(command_id=uuid4(), expected_version=1, action="cancel")
    )
    assert result["status"] == "cancelled"
    assert service.claim("lab-1") is None
    assert (
        service.store.get("alice", "session#" + str(request.session_id))["remote_active_run"]
        is None
    )


def cleanup(run, verified=True):
    return CleanupRequest(
        claim_token=run["claim_token"],
        command_id=uuid4(),
        reset_verified=verified,
        native_session_id=run["binding"]["native_session_id"],
        engine_version="fixture-engine",
        asset_version="fixture-assets",
        checks={key: verified for key in ("objects", "liquids", "tips", "controllers", "stopped")},
    )


def test_cleanup_failure_blocks_reuse_until_new_verified_receipt(system):
    service, _, request = system
    run, _ = start(system)
    service.unknown(
        "lab-1",
        request.run_id,
        UnknownRequest(claim_token=run["claim_token"], reason="Synthetic transport failure"),
    )
    receipt = cleanup(run, False)
    service.cleanup("lab-1", request.run_id, receipt)
    assert service.worker("lab-1")["state"] == "quarantined"
    assert not service.store.get("alice", "remote#" + str(request.session_id))["released"]
    assert "claim_token" not in service.get("alice", request.run_id)["cleanup"]
    good = cleanup(run)
    service.cleanup("lab-1", request.run_id, good)
    assert service.worker("lab-1")["state"] == "ready"
    assert service.store.get("alice", "remote#" + str(request.session_id))["released"]
    assert service.cleanup("lab-1", request.run_id, good)["cleanup"]["reset_verified"]


def test_machine_api_rejects_browser_user_and_forged_machine_identity(system):
    service, clock, _ = system
    api = TestClient(create_worker_app(service.store, enabled=True, clock=lambda: clock[0]))
    assert api.post("/internal/runs/claim").status_code == 403
    headers = {"Authorization": "Bearer lab-1." + "s" * 40}
    assert (
        api.post(
            "/internal/runs/claim", headers={**headers, "Origin": "https://academy.example"}
        ).status_code
        == 403
    )
    response = api.post("/internal/runs/claim", headers=headers)
    assert response.status_code == 200
    assert "owner" not in response.json()
    aws = TestClient(create_worker_app(service.store, runtime="aws", enabled=True))
    assert aws.post("/internal/runs/claim", headers=headers).status_code == 403
    assert aws.get("/api/sessions", headers=headers).status_code == 404


def test_native_gate_and_unqualified_worker_fail_closed(store):
    session = saved(store)
    request = SubmitRun(run_id=uuid4(), session_id=session["id"], expected_version=1)
    with pytest.raises(HTTPException) as error:
        RunService(store).submit("alice", request)
    assert error.value.status_code == 503
    worker(store, qualified=False)
    with pytest.raises(HTTPException):
        RunService(store, enabled=True).claim("lab-1")


def test_http_submission_locks_teaching_mutations(client, app):
    from test_learning import create, ready

    session = ready(client, create(client))
    app.state.runs.enabled = True
    worker(app.state.store)
    response = client.post(
        "/api/runs",
        json={
            "run_id": str(uuid4()),
            "session_id": session["id"],
            "expected_version": session["version"],
        },
    )
    assert response.status_code == 201, response.text
    current = client.get("/api/sessions/" + session["id"]).json()
    assert (
        client.post(
            "/api/sessions/" + session["id"] + "/start", json={"version": current["version"]}
        ).status_code
        == 409
    )
    assert (
        client.get("/api/sessions/" + session["id"] + "/remote-run").json()["run_id"]
        == response.json()["run_id"]
    )


def test_same_paused_snapshot_can_acknowledge_cancel(system):
    service, _, request = system
    run, _ = start(system)
    old = service.worker("lab-1")
    service.store.put(
        WORKERS, "lab-1", revised(old, controls=["pause", "resume", "cancel"]), old["version"]
    )
    body = snapshot(run, 0, 1).model_dump(mode="json")
    body["snapshot"]["status"] = "paused"
    service.snapshot("lab-1", request.run_id, SnapshotRequest.model_validate(body))
    current = service.get("alice", request.run_id)
    control = RunControl(command_id=uuid4(), expected_version=current["version"], action="cancel")
    service.control("alice", request.run_id, control)
    body["control_id"] = str(control.command_id)
    result = service.snapshot("lab-1", request.run_id, SnapshotRequest.model_validate(body))
    assert result["status"] == "cancelled"
    assert result["control"]["acknowledged"]


def test_cancel_during_unresolved_startup_is_explicitly_rejected(system):
    service, _, request = system
    run = service.claim("lab-1")
    with pytest.raises(Conflict):
        service.control(
            "alice",
            request.run_id,
            RunControl(command_id=uuid4(), expected_version=run["version"], action="cancel"),
        )
    assert service.raw(request.run_id)["status"] == "claimed"
