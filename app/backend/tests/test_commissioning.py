"""Synthetic commissioning control-plane tests, not GPU or live browser evidence."""

from uuid import uuid4

import pytest
from academy.auth import local_signer
from academy.commissioning import KEY, PARTITION, CommissioningRequest, authorize
from academy.recipes import CreateMixing, mixing_session
from academy.runs import (
    WORKERS,
    BindRequest,
    CleanupRequest,
    RunService,
    SnapshotRequest,
    StartRequest,
    SubmitRun,
)
from academy.store import Conflict
from fastapi import HTTPException
from test_dispatch import worker
from test_mixing import mixing_report


def setup(store, now, subject="alice", worker_id="pilot"):
    worker(
        store,
        worker_id,
        qualified=False,
        state="quarantined",
        scenes=[],
        controls=[],
        engine_version="a" * 40,
        asset_version="b" * 40,
    )
    request = CommissioningRequest(
        grant_id=uuid4(),
        subject=subject,
        worker_id=worker_id,
        engine_version="a" * 40,
        asset_version="b" * 40,
    )
    grant = authorize(store, request, clock=lambda: now)
    return request, grant


def submit(service, owner="alice", seed=42):
    session = mixing_session(CreateMixing(session_id=uuid4(), seed=seed))
    service.store.put(owner, f"session#{session['id']}", session, None)
    return service.submit(
        owner, SubmitRun(run_id=uuid4(), session_id=session["id"], expected_version=1)
    )


def test_browser_commissioning_does_not_enable_general_execution_or_qualify_worker(store):
    now = 1790863200
    request, grant = setup(store, now)
    service = RunService(store, False, clock=lambda: now)
    assert service.availability("alice")["enabled"]
    assert not service.availability("eve")["enabled"]
    for owner, seed in [("eve", 42), ("alice", 19)]:
        with pytest.raises(HTTPException):
            submit(service, owner, seed)
    run = submit(service)
    assert run["commissioning"] and run["status"] == "queued"
    worker(store, "wrong", scenes=["flex-mixing"])
    with pytest.raises(HTTPException):
        service.claim("wrong")
    claimed = service.claim("pilot")
    assert claimed["deadline"] <= grant["expires"]
    native = uuid4()
    service.start(
        "pilot", run["run_id"], StartRequest(claim_token=claimed["claim_token"], command_id=uuid4())
    )
    service.bind(
        "pilot",
        run["run_id"],
        BindRequest(
            claim_token=claimed["claim_token"],
            native_session_id=native,
            expected_revision=1,
            engine_version="a" * 40,
            asset_version="b" * 40,
        ),
    )
    _, _, body = mixing_report()
    body.update(
        run_id=run["run_id"],
        session_id=str(native),
        plan_hash=run["plan_hash"],
        engine_version="a" * 40,
        asset_version="b" * 40,
    )
    service.snapshot(
        "pilot", run["run_id"], SnapshotRequest(claim_token=claimed["claim_token"], snapshot=body)
    )
    service.cleanup(
        "pilot",
        run["run_id"],
        CleanupRequest(
            command_id=uuid4(),
            claim_token=claimed["claim_token"],
            native_session_id=native,
            engine_version="a" * 40,
            asset_version="b" * 40,
            reset_verified=True,
            checks={k: True for k in ("objects", "liquids", "tips", "controllers", "stopped")},
        ),
    )
    assert not store.get(WORKERS, "pilot")["qualified"]
    assert store.get(WORKERS, "pilot")["state"] == "quarantined"
    submit(service)
    with pytest.raises(HTTPException, match="409"):
        submit(service)
    assert not service.availability("alice")["enabled"]
    assert len(store.get(PARTITION, KEY)["run_ids"]) == 2


def test_expiry_wrong_pins_and_grant_retry_cannot_expand_authority(store):
    now = 1790863200
    request, grant = setup(store, now)
    assert authorize(store, request, clock=lambda: now + 30) == grant
    with pytest.raises(Conflict):
        authorize(store, request.model_copy(update={"max_runs": 1}), clock=lambda: now)
    expired = RunService(store, False, clock=lambda: grant["expires"] + 1)
    with pytest.raises(HTTPException):
        submit(expired)
    service = RunService(store, False, clock=lambda: now)
    run = submit(service)
    changed = store.get(WORKERS, "pilot")
    store.put(
        WORKERS,
        "pilot",
        {**changed, "version": changed["version"] + 1, "engine_version": "c" * 40},
        changed["version"],
    )
    with pytest.raises(HTTPException):
        service.claim("pilot")
    with pytest.raises(ValueError, match="Reconcile"):
        authorize(
            store,
            request.model_copy(update={"grant_id": uuid4()}),
            clock=lambda: grant["expires"] + 1,
        )
    assert service.raw(run["run_id"])["status"] == "queued"


def test_authenticated_catalog_and_report_are_scoped_to_operator_selected_subject(client, app):
    subject = local_signer(app.state.settings).loads(client.cookies.get("academy_local"))["sub"]
    _, grant = setup(app.state.store, 1790863200, subject)
    # Freeze service clock so this synthetic authorization is deterministic.
    app.state.runs.clock = lambda: 1790863200
    catalog = client.get("/api/simulations").json()
    assert catalog["enabled"] and catalog["commissioning"]
    assert client.get("/api/commissioning/report").json()["worker_qualified"] is False
    assert client.post("/api/commissioning/report", json={"subject": "eve"}).status_code == 405
    client.post("/api/auth/guest", json={"name": "Other"})
    assert not client.get("/api/simulations").json()["enabled"]
    assert client.get("/api/commissioning/report").status_code == 404


def test_pending_or_unknown_run_cannot_be_replaced_by_new_window(store):
    now = 1790863200
    request, grant = setup(store, now)
    service = RunService(store, False, clock=lambda: now)
    run = submit(service)
    claimed = service.claim("pilot")
    expired = RunService(store, False, clock=lambda: grant["expires"] + 1)
    with pytest.raises(HTTPException):
        expired.start(
            "pilot",
            run["run_id"],
            StartRequest(claim_token=claimed["claim_token"], command_id=uuid4()),
        )
    with pytest.raises(ValueError):
        authorize(
            store,
            request.model_copy(update={"grant_id": uuid4()}),
            clock=lambda: grant["expires"] + 2,
        )


def test_commissioning_video_uses_same_run_and_persists_browser_receipt(store):
    from academy.media import MediaService
    from test_media import Transport

    now = 1790863200
    setup(store, now)
    service = RunService(store, False, clock=lambda: now)
    public = submit(service)
    claimed = service.claim("pilot")
    service.start(
        "pilot",
        public["run_id"],
        StartRequest(claim_token=claimed["claim_token"], command_id=uuid4()),
    )
    service.bind(
        "pilot",
        public["run_id"],
        BindRequest(
            claim_token=claimed["claim_token"],
            native_session_id=uuid4(),
            expected_revision=1,
            engine_version="a" * 40,
            asset_version="b" * 40,
        ),
    )
    media = MediaService(service, Transport())
    media.publisher("pilot", public["run_id"], claimed["claim_token"])
    client_id = uuid4()
    media.viewer("alice", public["run_id"], client_id)
    media.viewer(
        "alice", public["run_id"], client_id, connect=False, frame_received=True, frames_decoded=100
    )
    proof = store.get("system#browser-evidence", public["run_id"])
    assert proof["frames_decoded"] == 100 and proof["source"] == "browser-report"
    assert proof["plan_hash"] == public["plan_hash"]
    with pytest.raises(HTTPException):
        media.viewer("eve", public["run_id"], uuid4())
    assert not store.get(WORKERS, "pilot")["qualified"]
