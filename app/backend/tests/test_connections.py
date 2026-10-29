"""SQLite/Dynamo control-plane fixtures, never physical or native acceptance."""

import copy
import secrets
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from academy.connections import (
    BINDINGS,
    DEVICE_LOCKS,
    INSTALLATIONS,
    PAIRINGS,
    QUALIFICATIONS,
    REAL_RUNS,
    ConnectionRevision,
    ConnectionService,
    ConnectionUpdate,
    ConnectorProbe,
    ConnectorReceipt,
    ConnectorResolution,
    PairRequest,
    RealRunRequest,
    digest,
)
from academy.remote_run import RemoteRunRequest, workflow_digest
from academy.runs import RUNS, WORKERS, revised
from academy.store import Conflict
from academy.teaching import new_session
from fastapi import HTTPException
from test_dispatch import worker
from test_native_studio import capability, design
from test_studio_commissioning import completed_snapshot

RELEASE = {
    "status": "approved",
    "instrument": "flex",
    "platform": "linux",
    "release_id": "flex-test-1",
    "artifact_sha256": "a" * 64,
    "source_commit": "b" * 40,
    "supported_firmware": ["8.8.2"],
    "execution_transport": "opentrons-protocol-engine",
    "runtime_contract_id": "runtime-fixture/1",
    "runtime_release_id": "runtime-fixture-1",
    "runtime_bundle_sha256": "d" * 64,
}
PROBE = {
    "instrument": "flex",
    "serial": "FLEX-TEST-01",
    "release_id": RELEASE["release_id"],
    "artifact_sha256": RELEASE["artifact_sha256"],
    "profile_sha256": "c" * 64,
    "source_commit": RELEASE["source_commit"],
    "firmware": "8.8.2",
    "capabilities": ["protocol-engine"],
    "reachable": True,
    "runtime_contract_id": RELEASE["runtime_contract_id"],
    "runtime_release_id": RELEASE["runtime_release_id"],
    "runtime_bundle_sha256": RELEASE["runtime_bundle_sha256"],
}


@pytest.fixture
def connectors(store):
    now = [1790000000.0]
    release = copy.deepcopy(RELEASE)
    service = ConnectionService(
        store, enabled=True, approved_release=lambda *args: release, clock=lambda: now[0]
    )
    return service, now, release


def connection(service, owner="alice", instrument="flex"):
    return service.save(
        owner,
        uuid4(),
        ConnectionUpdate(
            expected_version=0,
            instrument=instrument,
            display_name="Lab instrument",
            platform="linux",
        ),
    )


def pair(service, owner="alice", device=None):
    device = device or connection(service, owner)
    issue = service.pairing(
        owner, device["id"], ConnectionRevision(expected_version=device["version"])
    )
    data = PairRequest(
        code=issue["code"], installation_id=uuid4(), secret=secrets.token_urlsafe(32)
    )
    result = service.redeem(data)
    token = f"Bearer {data.installation_id}.{data.secret}"
    return result["connection"], service.authenticate(token), data, token


def qualify(service, connection_id):
    device = service.raw("alice", connection_id)
    qualification = {
        "version": 1,
        "owner": "alice",
        "connection_id": device["id"],
        "installation_id": device["installation_id"],
        "revoked": False,
        "expires_at": service.clock() + 3600,
        "capabilities": ["protocol-engine"],
        **{key: device["probe"][key] for key in BINDINGS},
    }
    service.store.put(QUALIFICATIONS, connection_id, qualification, None)
    return qualification


def native_fixture(service, plan=None):
    """Synthetic durable native records exercise checks; these are not GPU evidence."""
    plan = plan or design()
    session = new_session(plan)
    run_id, native_id = str(uuid4()), str(uuid4())
    request = RemoteRunRequest(
        run_id=run_id, expected_revision=1, experiment=plan, plan_hash=workflow_digest(plan)
    )
    snapshot = completed_snapshot(native_id, request)
    if not service.store.get(WORKERS, "lab-1"):
        worker(
            service.store,
            scenes=["workflow-studio-flex"],
            capabilities={"workflow-studio-flex": capability().model_dump()},
            engine_version=snapshot["engine_version"],
            asset_version=snapshot["asset_version"],
        )
    raw = {
        "version": 1,
        "run_id": run_id,
        "owner": "alice",
        "session_id": session["id"],
        "plan": plan.model_dump(mode="json"),
        "plan_hash": workflow_digest(plan),
        "status": "completed",
        "worker_id": "lab-1",
        "snapshot": snapshot,
        "binding": {"native_session_id": native_id, "expected_revision": 1},
        "cleanup": {
            "reset_verified": True,
            "native_session_id": native_id,
            "engine_version": snapshot["engine_version"],
            "asset_version": snapshot["asset_version"],
            "checks": dict.fromkeys(["objects", "liquids", "tips", "controllers", "stopped"], True),
        },
    }
    service.store.put("alice", f"session#{session['id']}", session, None)
    service.store.put(
        "alice", f"remote#{session['id']}", {"version": 1, "run_id": run_id, "released": True}, None
    )
    service.store.put(RUNS, run_id, raw, None)
    return session, raw


def ready(service):
    device, installation, _, token = pair(service)
    service.probe(installation, ConnectorProbe(**PROBE))
    qualify(service, device["id"])
    session, native = native_fixture(service)
    device = service.get("alice", device["id"])
    request = RealRunRequest(
        run_id=uuid4(),
        expected_version=device["version"],
        session_id=session["id"],
        session_version=session["version"],
        native_run_id=native["run_id"],
        acknowledge_physical_motion=True,
    )
    return device, installation, token, session, native, request


def receipt(command, **changes):
    return ConnectorReceipt(
        command_id=command["run_id"],
        connection_id=command["connection_id"],
        installation_id=command["installation_id"],
        plan_hash=command["plan_hash"],
        **{key: command[key] for key in BINDINGS},
        **{
            "outcome": "completed",
            "protocol_id": "protocol-fixture",
            "robot_run_id": "pe-fixture",
            "completed_actions": len(command["plan"]["actions"]),
            "stop_confirmed": True,
            "detail": "Software fixture only",
            **changes,
        },
    )


def test_connection_owner_scope_and_strict_versions(connectors):
    service, _, _ = connectors
    device = connection(service)
    assert service.list("alice")["connections"][0]["id"] == device["id"]
    assert service.list("bob") == {"connections": []}
    with pytest.raises(HTTPException) as error:
        service.get("bob", device["id"])
    assert error.value.status_code == 404
    with pytest.raises(Conflict):
        service.save(
            "alice",
            device["id"],
            ConnectionUpdate(
                expected_version=0, instrument="flex", display_name="stale", platform="linux"
            ),
        )
    assert service.get("alice", device["id"])["version"] == 1


def test_pair_is_hashed_atomic_single_use_and_lost_reply_recovers(connectors):
    service, _, _ = connectors
    device, installation, data, token = pair(service)
    assert device["status"] == "paired" and not device["qualified"]
    assert service.redeem(data)["connection"] == device
    saved = service.store.get(PAIRINGS, digest(data.code))
    assert data.code not in str(saved) and data.secret not in str(saved)
    assert data.secret not in str(service.store.get(INSTALLATIONS, str(data.installation_id)))
    assert "token_digest" not in str(service.machine_public(installation))
    with pytest.raises(HTTPException):
        service.redeem(data.model_copy(update={"installation_id": uuid4()}))
    with pytest.raises(HTTPException):
        service.redeem(data.model_copy(update={"secret": "z" * 43}))
    revoked = service.revoke(
        "alice", device["id"], ConnectionRevision(expected_version=device["version"])
    )
    assert revoked["status"] == "revoked"
    with pytest.raises(HTTPException):
        service.authenticate(token)
    with pytest.raises(HTTPException):
        service.redeem(data)


def test_pair_expiry_new_code_invalidates_old_and_cannot_replace_live_installation(connectors):
    service, now, _ = connectors
    device = connection(service)
    first = service.pairing("alice", device["id"], ConnectionRevision(expected_version=1))
    second = service.pairing("alice", device["id"], ConnectionRevision(expected_version=2))
    data = PairRequest(
        code=first["code"], installation_id=uuid4(), secret=secrets.token_urlsafe(32)
    )
    with pytest.raises(HTTPException):
        service.redeem(data)
    now[0] = second["expires_at"]
    with pytest.raises(HTTPException):
        service.redeem(data.model_copy(update={"code": second["code"]}))
    result = service.pairing("alice", device["id"], ConnectionRevision(expected_version=3))
    device = service.redeem(data.model_copy(update={"code": result["code"]}))["connection"]
    with pytest.raises(HTTPException):
        service.pairing(
            "alice", device["id"], ConnectionRevision(expected_version=device["version"])
        )


def test_two_installations_cannot_redeem_one_pair_code(connectors):
    service, _, _ = connectors
    device = connection(service)
    issued = service.pairing("alice", device["id"], ConnectionRevision(expected_version=1))
    payloads = [
        PairRequest(code=issued["code"], installation_id=uuid4(), secret=secrets.token_urlsafe(32))
        for _ in range(2)
    ]

    def redeem(data):
        try:
            service.redeem(data)
            return True
        except (Conflict, HTTPException):
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(redeem, payloads))
    assert results.count(True) == 1
    assert len(service.store.partition(INSTALLATIONS)) == 1


def test_probe_never_self_qualifies_and_release_is_fail_closed(connectors):
    service, _, release = connectors
    device, machine, _, _ = pair(service)
    result = service.probe(machine, ConnectorProbe(**PROBE))
    assert not result["connection"]["qualified"]
    qualify(service, device["id"])
    assert service.get("alice", device["id"])["qualified"]
    release["status"] = "candidate"
    assert not service.get("alice", device["id"])["qualified"]
    assert service.get("alice", device["id"])["approved_release"] is None
    disabled = ConnectionService(service.store)
    assert disabled.get("alice", device["id"])["approved_release"] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("profile_sha256", "d" * 64),
        ("serial", "OTHER-ROBOT"),
        ("source_commit", "e" * 40),
        ("firmware", "9.0.0"),
        ("release_id", "other-release"),
        ("artifact_sha256", "f" * 64),
    ],
)
def test_probe_identity_changes_invalidate_operator_qualification(connectors, field, value):
    service, _, _ = connectors
    device, installation, *_ = ready(service)
    service.probe(installation, ConnectorProbe(**{**PROBE, field: value}))
    assert not service.get("alice", device["id"])["qualified"]


@pytest.mark.parametrize(
    "mutation",
    [
        "synthetic",
        "missing_snapshot",
        "incomplete_steps",
        "other_owner",
        "other_session",
        "changed_plan",
        "unqualified_worker",
        "revoked_worker",
        "missing_capability",
        "unreleased",
        "no_reset",
        "missing_reset_check",
        "changed_native_binding",
        "wrong_engine",
        "changed_layout",
    ],
)
def test_native_gate_rejects_every_missing_or_mismatched_proof(connectors, mutation):
    service, _, _ = connectors
    device, _, _, session, native, request = ready(service)
    owner, key, item = RUNS, native["run_id"], copy.deepcopy(native)
    if mutation == "synthetic":
        item["snapshot"]["evidence"] = "synthetic"
    elif mutation == "missing_snapshot":
        item["snapshot"] = None
    elif mutation == "incomplete_steps":
        item["snapshot"]["steps"].pop()
    elif mutation == "other_owner":
        item["owner"] = "bob"
    elif mutation == "other_session":
        item["session_id"] = str(uuid4())
    elif mutation == "changed_plan":
        owner, key, item = "alice", f"session#{session['id']}", copy.deepcopy(session)
        item["experiment"]["source_volume"] = 1100
    elif mutation in {"unqualified_worker", "revoked_worker", "missing_capability"}:
        owner, key = WORKERS, "lab-1"
        item = service.store.get(owner, key)
        if mutation == "unqualified_worker":
            item["qualified"] = False
        elif mutation == "revoked_worker":
            item["revoked"] = True
        else:
            item["capabilities"] = {}
    elif mutation == "unreleased":
        owner, key = "alice", f"remote#{session['id']}"
        item = service.store.get(owner, key)
        item["released"] = False
    elif mutation == "no_reset":
        item["cleanup"]["reset_verified"] = False
    elif mutation == "missing_reset_check":
        del item["cleanup"]["checks"]["stopped"]
    elif mutation == "changed_native_binding":
        item["binding"]["native_session_id"] = str(uuid4())
    elif mutation == "wrong_engine":
        item["snapshot"]["engine_version"] = "unqualified-version"
    elif mutation == "changed_layout":
        item["snapshot"]["native_state"]["studio"]["labware_slots"]["tips"] = "C1"
    service.store.put(owner, key, revised(item), item["version"])
    report = service.preflight("alice", device["id"], session["id"])
    assert "native_evidence" in {issue["code"] for issue in report["issues"]}
    if mutation == "changed_plan":
        request = request.model_copy(update={"session_version": 2})
    with pytest.raises(HTTPException):
        service.submit("alice", device["id"], request)
    assert service.store.partition(REAL_RUNS) == []


def test_complete_authorized_path_and_identical_receipt_recovery(connectors):
    service, _, _ = connectors
    device, installation, _, session, _, request = ready(service)
    assert service.preflight("alice", device["id"], session["id"])["ready"]
    queued = service.submit("alice", device["id"], request)
    assert service.submit("alice", device["id"], request) == queued
    command = service.claim(installation)
    assert command["status"] == "claimed" and service.claim(installation) is None
    assert command["plan_hash"] == queued["plan_hash"]
    assert service.command_public(service.machine_run(installation, queued["run_id"])) == command
    evidence = receipt(command)
    done = service.receipt(installation, queued["run_id"], evidence)
    assert done["status"] == "completed"
    assert service.receipt(installation, queued["run_id"], evidence) == done
    assert service.get("alice", device["id"])["active_run_id"] is None
    assert service.store.partition(DEVICE_LOCKS)[0]["active_run_id"] is None
    with pytest.raises(Conflict):
        service.receipt(
            installation, queued["run_id"], evidence.model_copy(update={"detail": "different"})
        )
    assert service.claim(installation) is None


@pytest.mark.parametrize("change", ["disable", "qualification", "release", "plan", "expired_probe"])
def test_queued_claim_rechecks_authority_and_never_replays(connectors, change):
    service, now, release = connectors
    device, installation, _, session, _, request = ready(service)
    queued = service.submit("alice", device["id"], request)
    if change == "disable":
        service.enabled = False
    elif change == "qualification":
        qualification = service.store.get(QUALIFICATIONS, device["id"])
        service.store.put(
            QUALIFICATIONS,
            device["id"],
            revised(qualification, revoked=True),
            qualification["version"],
        )
    elif change == "release":
        release["artifact_sha256"] = "d" * 64
    elif change == "plan":
        session["experiment"]["source_volume"] = 1100
        service.store.put("alice", f"session#{session['id']}", revised(session), session["version"])
    else:
        now[0] += 301
    assert service.claim(installation) is None
    assert service.get_run("alice", device["id"], queued["run_id"])["status"] == "unknown"
    assert service.get("alice", device["id"])["active_run_id"] == queued["run_id"]


def test_command_expiry_late_receipt_never_clears_unknown_lock(connectors):
    service, now, _ = connectors
    device, installation, _, _, _, request = ready(service)
    service.submit("alice", device["id"], request)
    command = service.claim(installation)
    now[0] = command["expires_at"]
    assert service.get_run("alice", device["id"], request.run_id)["status"] == "unknown"
    assert service.receipt(installation, request.run_id, receipt(command))["status"] == "unknown"
    assert service.get("alice", device["id"])["active_run_id"] == str(request.run_id)
    assert service.claim(installation) is None


@pytest.mark.parametrize("change", ["qualification", "catalog", "disable"])
def test_authority_revocation_after_claim_withdraws_command_before_local_play(connectors, change):
    service, _, release = connectors
    device, installation, _, _, _, request = ready(service)
    service.submit("alice", device["id"], request)
    service.claim(installation)
    if change == "qualification":
        qualification = service.store.get(QUALIFICATIONS, device["id"])
        service.store.put(
            QUALIFICATIONS,
            device["id"],
            revised(qualification, revoked=True),
            qualification["version"],
        )
    elif change == "catalog":
        release["status"] = "candidate"
    else:
        service.enabled = False
    current = service.command_public(service.machine_run(installation, request.run_id))
    assert current["status"] == "unknown" and current["stop_requested"]
    assert service.get("alice", device["id"])["active_run_id"] == str(request.run_id)
    assert service.claim(installation) is None


def test_receipt_bound_to_exact_command_and_stopped_full_plan(connectors):
    service, _, _ = connectors
    device, installation, *_rest, request = ready(service)
    service.submit("alice", device["id"], request)
    command = service.claim(installation)
    for field, value in [
        ("plan_hash", "f" * 64),
        ("installation_id", uuid4()),
        ("connection_id", uuid4()),
        ("command_id", uuid4()),
        ("serial", "OTHER"),
    ]:
        with pytest.raises(Conflict):
            service.receipt(
                installation, request.run_id, receipt(command).model_copy(update={field: value})
            )
    for changes in [{"completed_actions": 1}, {"stop_confirmed": False}, {"robot_run_id": None}]:
        with pytest.raises(HTTPException):
            service.receipt(installation, request.run_id, receipt(command, **changes))
    unknown = service.receipt(
        installation, request.run_id, receipt(command, outcome="failed", stop_confirmed=False)
    )
    assert unknown["status"] == "unknown"
    assert service.get("alice", device["id"])["active_run_id"] == str(request.run_id)


def test_stop_before_claim_cancels_without_motion_and_stop_after_claim_is_only_request(connectors):
    service, _, _ = connectors
    device, installation, _, _, _, request = ready(service)
    queued = service.submit("alice", device["id"], request)
    stopped = service.stop(
        "alice",
        device["id"],
        request.run_id,
        ConnectionRevision(expected_version=queued["version"]),
    )
    assert stopped["status"] == "stopped" and service.claim(installation) is None
    device = service.get("alice", device["id"])
    assert device["active_run_id"] is None
    request = request.model_copy(update={"run_id": uuid4(), "expected_version": device["version"]})
    service.submit("alice", device["id"], request)
    command = service.claim(installation)
    stopping = service.stop(
        "alice",
        device["id"],
        request.run_id,
        ConnectionRevision(expected_version=command["version"]),
    )
    assert stopping["status"] == "claimed" and stopping["stop_requested"]
    assert service.get("alice", device["id"])["active_run_id"] == str(request.run_id)
    assert (
        service.receipt(
            installation, request.run_id, receipt(command, outcome="stopped", completed_actions=0)
        )["status"]
        == "stopped"
    )


def test_revoke_during_claim_locks_device_and_invalidates_pending_machine_context(connectors):
    service, _, _ = connectors
    device, installation, token, _, _, request = ready(service)
    service.submit("alice", device["id"], request)
    command = service.claim(installation)
    device = service.get("alice", device["id"])
    service.revoke("alice", device["id"], ConnectionRevision(expected_version=device["version"]))
    with pytest.raises(HTTPException):
        service.authenticate(token)
    with pytest.raises(Conflict):
        service.receipt(installation, request.run_id, receipt(command))
    assert service.get_run("alice", device["id"], request.run_id)["status"] == "unknown"
    assert service.get("alice", device["id"])["active_run_id"] == str(request.run_id)


def test_operator_flag_ot2_and_stale_revision_cannot_submit(connectors):
    service, _, _ = connectors
    device, _, _, session, _, request = ready(service)
    with pytest.raises(Conflict):
        service.submit("alice", device["id"], request.model_copy(update={"expected_version": 1}))
    with pytest.raises(HTTPException):
        service.submit(
            "alice", device["id"], request.model_copy(update={"acknowledge_physical_motion": False})
        )
    service.enabled = False
    with pytest.raises(HTTPException):
        service.submit("alice", device["id"], request)
    service.enabled = True
    other = connection(service, instrument="ot2")
    report = service.preflight("alice", other["id"], session["id"])
    assert "native_unsupported" in {issue["code"] for issue in report["issues"]}


def test_duplicate_claim_is_atomic(connectors):
    service, _, _ = connectors
    device, installation, _, _, _, request = ready(service)
    service.submit("alice", device["id"], request)
    with ThreadPoolExecutor(max_workers=2) as pool:
        commands = list(pool.map(lambda _: service.claim(installation), range(2)))
    assert sum(command is not None for command in commands) == 1


def test_global_device_lock_prevents_second_owner_or_connection(connectors):
    service, _, _ = connectors
    first, installation, _, session, _, request = ready(service)
    second, second_installation, _, _ = pair(service)
    service.probe(second_installation, ConnectorProbe(**PROBE))
    qualify(service, second["id"])
    service.submit("alice", first["id"], request)
    report = service.preflight("alice", second["id"], session["id"])
    assert "device_locked" in {issue["code"] for issue in report["issues"]}
    assert not report["ready"]
    assert service.claim(installation) is not None


def resolution_for(command, version, **changes):
    return ConnectorResolution(
        expected_version=version,
        resolution_id=uuid4(),
        connection_id=command["connection_id"],
        installation_id=command["installation_id"],
        plan_hash=command["plan_hash"],
        **{key: command[key] for key in BINDINGS},
        **{
            "protocol_id": "protocol-fixture",
            "robot_run_id": "pe-fixture",
            "no_run_created": False,
            "stopped": True,
            "released": True,
            "operator_id": "software-fixture-operator",
            "evidence_sha256": "e" * 64,
            "detail": "Fixture reconciliation, not physical verification",
            **changes,
        },
    )


def test_offline_resolution_preserves_unknown_receipt_and_stale_retry_cannot_unlock_new_run(
    connectors,
):
    service, now, _ = connectors
    device, installation, _, _, _, request = ready(service)
    service.submit("alice", device["id"], request)
    command = service.claim(installation)
    now[0] = command["expires_at"]
    evidence = receipt(command)
    unknown = service.receipt(installation, request.run_id, evidence)
    assert unknown["status"] == "unknown"
    data = resolution_for(command, unknown["version"])
    reconciled = service.resolve_unknown(request.run_id, data)
    assert reconciled["status"] == "unknown" and reconciled["receipt"] == unknown["receipt"]
    assert reconciled["resolution"]["replay_authorized"] is False
    assert service.get("alice", device["id"])["active_run_id"] is None
    assert service.store.partition(DEVICE_LOCKS)[0]["active_run_id"] is None
    service.probe(installation, ConnectorProbe(**PROBE))
    device = service.get("alice", device["id"])
    new_request = request.model_copy(
        update={"run_id": uuid4(), "expected_version": device["version"]}
    )
    service.submit("alice", device["id"], new_request)
    assert service.resolve_unknown(request.run_id, data) == reconciled
    with pytest.raises(Conflict):
        service.resolve_unknown(request.run_id, data.model_copy(update={"resolution_id": uuid4()}))
    assert service.get("alice", device["id"])["active_run_id"] == str(new_request.run_id)
    assert service.store.partition(DEVICE_LOCKS)[0]["active_run_id"] == str(new_request.run_id)


def test_offline_resolution_requires_unknown_exact_binding_and_current_version(connectors):
    service, _, _ = connectors
    device, installation, _, _, _, request = ready(service)
    service.submit("alice", device["id"], request)
    command = service.claim(installation)
    data = resolution_for(command, command["version"])
    with pytest.raises(Conflict):
        service.resolve_unknown(request.run_id, data)
    unknown = service.receipt(
        installation, request.run_id, receipt(command, outcome="unknown", stop_confirmed=False)
    )
    data = data.model_copy(update={"expected_version": unknown["version"]})
    for field, value in [
        ("expected_version", 1),
        ("serial", "OTHER"),
        ("robot_run_id", "other-run"),
        ("protocol_id", "other-protocol"),
        ("installation_id", uuid4()),
        ("plan_hash", "f" * 64),
    ]:
        with pytest.raises(Conflict):
            service.resolve_unknown(request.run_id, data.model_copy(update={field: value}))
    assert service.get("alice", device["id"])["active_run_id"] == str(request.run_id)


def test_offline_resolution_no_created_robot_run_must_be_explicit(connectors):
    service, now, _ = connectors
    device, installation, _, _, _, request = ready(service)
    service.submit("alice", device["id"], request)
    command = service.claim(installation)
    now[0] = command["expires_at"]
    unknown = service.get_run("alice", device["id"], request.run_id)
    data = resolution_for(
        command, unknown["version"], no_run_created=True, protocol_id=None, robot_run_id=None
    )
    assert service.resolve_unknown(request.run_id, data)["status"] == "unknown"
    assert service.get("alice", device["id"])["active_run_id"] is None
