"""Synthetic control-plane tests; no GPU, browser-login or hardware acceptance."""

from copy import deepcopy
from uuid import uuid4

import pytest
from academy.commissioning import (
    KEY,
    PARTITION,
    CommissioningRequest,
    active_grant,
    authorize,
    permits_plan,
    reserve,
)
from academy.media import MediaService
from academy.models import Action, Experiment
from academy.native_studio_runtime import flex_capability
from academy.remote_run import RemoteRunRequest, workflow_digest
from academy.runs import (
    RUNS,
    WORKERS,
    BindRequest,
    CleanupRequest,
    RunService,
    SnapshotRequest,
    StartRequest,
    SubmitRun,
)
from academy.runtime_inventory import PROFILE
from academy.store import Conflict
from academy.teaching import new_session
from fastapi import HTTPException
from pydantic import ValidationError
from test_dispatch import worker
from test_media import Transport
from test_remote_run import report

NOW = 1790863200


def approved_request():
    plans = [
        Experiment(
            title="Native Studio acceptance",
            course_id="workflow-sandbox",
            instrument="flex",
            diluent_volume=0,
            layout={
                "tips": "B1" if volume == 100 else "C1",
                "stock": "D1",
                "plate": "D2",
                "waste": "D3",
            },
            actions=[
                Action(kind="pickup"),
                Action(kind="aspirate", well="stock", volume=volume),
                Action(kind="dispense", well="A1", volume=volume),
                Action(kind="drop"),
            ],
        )
        for volume in (100, 50)
    ]
    return CommissioningRequest.model_validate(
        {
            "grant_id": str(uuid4()),
            "subject": "alice",
            "worker_id": "pilot",
            "engine_version": PROFILE["engine_commit"],
            "asset_version": PROFILE["asset_commit"],
            "studio": {
                "scene": "workflow-studio-flex",
                "instrument": "flex",
                "capability": flex_capability(),
                "plans": [
                    {"experiment": plan.model_dump(mode="json"), "plan_hash": workflow_digest(plan)}
                    for plan in plans
                ],
            },
        }
    )


def setup_studio(store):
    request = approved_request()
    worker(
        store,
        "pilot",
        qualified=False,
        state="quarantined",
        scenes=[],
        capabilities={},
        controls=[],
        engine_version=request.engine_version,
        asset_version=request.asset_version,
    )
    grant = authorize(store, request, clock=lambda: NOW)
    return request, grant, RunService(store, enabled=False, clock=lambda: NOW)


def saved(store, plan, owner="alice"):
    session = new_session(plan)
    store.put(owner, "session#" + session["id"], session, None)
    return SubmitRun(run_id=uuid4(), session_id=session["id"], expected_version=1)


def completed_snapshot(native, request):
    snapshot = report(native, request, completed=len(request.experiment.actions))
    snapshot.update(engine_version=PROFILE["engine_commit"], asset_version=PROFILE["asset_commit"])
    volume = request.experiment.actions[1].volume
    snapshot["native_state"].update(
        pipette_volume_ul=0,
        tip_attached=False,
        well_volumes_ul={
            "stock": request.experiment.source_volume - volume,
            "A1": volume,
            "A2": 0,
            "A3": 0,
        },
        studio={
            "scene": "workflow-studio-flex",
            "instrument": "flex",
            "observation_model": "native-semantic",
            "waste_volume_ul": 0,
            "labware_slots": request.experiment.layout,
            "native_action_index": 20,
            "native_action_count": 20,
            "native_action": "Completed",
        },
    )
    return snapshot


@pytest.mark.parametrize(
    "case",
    [
        "hash",
        "changed_plan",
        "same_plan",
        "one_plan",
        "scene",
        "viewport",
        "observations",
        "unsafe_order",
        "pins",
        "one_run",
    ],
)
def test_studio_authority_is_exact_and_requires_reviewed_capability(case):
    request = approved_request().model_dump(mode="json")
    scope = request["studio"]
    if case == "hash":
        scope["plans"][0]["plan_hash"] = "f" * 64
    elif case == "changed_plan":
        scope["plans"][0]["experiment"]["title"] = "Different saved plan"
    elif case == "same_plan":
        scope["plans"][1] = deepcopy(scope["plans"][0])
    elif case == "one_plan":
        scope["plans"].pop()
    elif case == "scene":
        scope["scene"] = "workflow-studio-ot2"
    elif case == "viewport":
        scope["capability"]["viewport"] = False
    elif case == "observations":
        scope["capability"]["observed"] = ["tip_state"]
    elif case == "unsafe_order":
        plan = Experiment.model_validate(scope["plans"][0]["experiment"])
        plan.actions.pop(0)
        scope["plans"][0] = {
            "experiment": plan.model_dump(mode="json"),
            "plan_hash": workflow_digest(plan),
        }
    elif case == "pins":
        request["engine_version"] = "e" * 40
    else:
        request["max_runs"] = 1
    with pytest.raises(ValidationError):
        CommissioningRequest.model_validate(request)


def test_legacy_scope_bytes_and_exact_approval_retry_are_preserved(store):
    request, grant, _ = setup_studio(store)
    assert authorize(store, request, clock=lambda: NOW + 60) == grant
    changed = request.model_copy(update={"subject": "bob"})
    with pytest.raises(Conflict):
        authorize(store, changed, clock=lambda: NOW)
    legacy = request.model_dump(mode="json")
    del legacy["studio"]
    assert CommissioningRequest.model_validate(legacy).model_dump(mode="json") == legacy
    assert "studio" not in CommissioningRequest.model_validate(
        {**legacy, "studio": None}
    ).model_dump(mode="json")
    assert not store.get(WORKERS, "pilot")["qualified"]
    assert store.get(WORKERS, "pilot")["capabilities"] == {}


def test_reservations_bind_exact_order_and_cannot_expand_after_two_runs(store):
    request, grant, _ = setup_studio(store)
    first, second = [item.experiment for item in request.studio.plans]
    assert permits_plan(grant, first, next_only=True)
    assert permits_plan(grant, second) and not permits_plan(grant, second, next_only=True)
    with pytest.raises(ValueError):
        reserve(grant, str(uuid4()), second)
    with pytest.raises(ValueError):
        reserve(grant, str(uuid4()))
    for index, plan in enumerate((first, second)):
        run_id = str(uuid4())
        write = reserve(grant, run_id, plan)
        store.transact([write])
        grant = store.get(PARTITION, KEY)
        assert len(grant["run_ids"]) == index + 1
        assert grant["run_plan_hashes"][run_id] == workflow_digest(plan)
        with pytest.raises(ValueError):
            reserve(grant, run_id, plan)
    assert not permits_plan(grant, second, next_only=True)
    with pytest.raises(ValueError):
        reserve(grant, str(uuid4()), first)


def test_two_studio_runs_use_scoped_preflight_dispatch_media_cleanup_without_global_enable(store):
    approval, _, service = setup_studio(store)
    first, second = [entry.experiment for entry in approval.studio.plans]
    for plan, owner in (
        (second, "alice"),
        (first, "eve"),
        (first.model_copy(update={"title": "Changed"}), "alice"),
    ):
        command = saved(store, plan, owner)
        assert not service.studio_preflight(owner, str(command.session_id))["ready"]
        with pytest.raises(HTTPException):
            service.submit(owner, command)
    worker(
        store,
        "wrong",
        qualified=True,
        scenes=[approval.studio.scene],
        capabilities={approval.studio.scene: flex_capability()},
        engine_version=approval.engine_version,
        asset_version=approval.asset_version,
    )
    for plan in (first, second):
        command = saved(store, plan)
        assert service.studio_preflight("alice", str(command.session_id))["ready"]
        public = service.submit("alice", command)
        assert public["scene"] == approval.studio.scene
        # Refresh/retry reads the same run, never consumes a second authorization.
        assert service.submit("alice", command) == public
        assert service.for_session("alice", str(command.session_id))["run_id"] == public["run_id"]
        with pytest.raises(HTTPException):
            service.claim("wrong")
        claimed = service.claim("pilot")
        assert claimed["run_id"] == public["run_id"]
        service.start(
            "pilot",
            public["run_id"],
            StartRequest(claim_token=claimed["claim_token"], command_id=uuid4()),
        )
        native = uuid4()
        service.bind(
            "pilot",
            public["run_id"],
            BindRequest(
                claim_token=claimed["claim_token"],
                native_session_id=native,
                expected_revision=1,
                engine_version=approval.engine_version,
                asset_version=approval.asset_version,
            ),
        )
        transport = Transport()
        media = MediaService(service, transport)
        publisher = media.publisher("pilot", public["run_id"], claimed["claim_token"])
        client_id = uuid4()
        viewer = media.viewer("alice", public["run_id"], client_id)
        assert viewer["plan_hash"] == publisher["plan_hash"] == workflow_digest(plan)
        media.viewer(
            "alice",
            public["run_id"],
            client_id,
            connect=False,
            frame_received=True,
            frames_decoded=50,
        )
        with pytest.raises(HTTPException):
            media.viewer("eve", public["run_id"], uuid4())
        request = RemoteRunRequest(
            run_id=command.run_id,
            expected_revision=1,
            experiment=plan,
            plan_hash=workflow_digest(plan),
        )
        service.snapshot(
            "pilot",
            public["run_id"],
            SnapshotRequest(
                claim_token=claimed["claim_token"], snapshot=completed_snapshot(native, request)
            ),
        )
        service.cleanup(
            "pilot",
            public["run_id"],
            CleanupRequest(
                command_id=uuid4(),
                claim_token=claimed["claim_token"],
                native_session_id=native,
                engine_version=approval.engine_version,
                asset_version=approval.asset_version,
                reset_verified=True,
                checks=dict.fromkeys(
                    ("objects", "liquids", "tips", "controllers", "stopped"), True
                ),
            ),
        )
        assert store.get("alice", f"session#{command.session_id}")["remote_active_run"] is None
        assert not store.get(WORKERS, "pilot")["qualified"]
        assert store.get(WORKERS, "pilot")["state"] == "quarantined"
        assert store.get(WORKERS, "pilot")["capabilities"] == {}
    assert len(store.get(PARTITION, KEY)["run_ids"]) == 2
    assert not service.availability("alice")["enabled"]
    assert not service.enabled


@pytest.mark.parametrize("case", ["plan", "hash", "scene", "reservation", "worker_pin", "subject"])
def test_queued_studio_claim_rechecks_exact_bound_grant(store, case):
    approval, _, service = setup_studio(store)
    command = saved(store, approval.studio.plans[0].experiment)
    public = service.submit("alice", command)
    run = service.raw(public["run_id"])
    if case == "plan":
        run["plan"]["title"] = "Tampered after submission"
    elif case == "hash":
        run["plan_hash"] = "f" * 64
    elif case == "scene":
        run["scene"] = "workflow-studio-ot2"
    elif case == "subject":
        run["owner"] = "eve"
    elif case == "reservation":
        grant = store.get(PARTITION, KEY)
        grant["run_plan_hashes"][run["run_id"]] = "f" * 64
        store.put(PARTITION, KEY, {**grant, "version": grant["version"] + 1}, grant["version"])
    else:
        registered = store.get(WORKERS, "pilot")
        store.put(
            WORKERS,
            "pilot",
            {**registered, "engine_version": "c" * 40, "version": registered["version"] + 1},
            registered["version"],
        )
    store.put(RUNS, run["run_id"], {**run, "version": run["version"] + 1}, run["version"])
    assert active_grant(store, NOW, run=run) is None
    # The nominated worker is still authenticated; it cannot receive this altered run.
    if case == "worker_pin":
        with pytest.raises(HTTPException) as failure:
            service.claim("pilot")
        assert failure.value.status_code == 403
    else:
        assert service.claim("pilot") is None


def test_mutated_started_studio_plan_revokes_media_without_qualification(store):
    approval, _, service = setup_studio(store)
    public = service.submit("alice", saved(store, approval.studio.plans[0].experiment))
    claim = service.claim("pilot")
    service.start(
        "pilot",
        public["run_id"],
        StartRequest(claim_token=claim["claim_token"], command_id=uuid4()),
    )
    service.bind(
        "pilot",
        public["run_id"],
        BindRequest(
            claim_token=claim["claim_token"],
            native_session_id=uuid4(),
            expected_revision=1,
            engine_version=approval.engine_version,
            asset_version=approval.asset_version,
        ),
    )
    media = MediaService(service, Transport())
    media.publisher("pilot", public["run_id"], claim["claim_token"])
    run = service.raw(public["run_id"])
    run["plan_hash"] = "f" * 64
    store.put(RUNS, run["run_id"], {**run, "version": run["version"] + 1}, run["version"])
    with pytest.raises(HTTPException):
        media.viewer("alice", public["run_id"], uuid4())
    with pytest.raises(HTTPException):
        media.publisher("pilot", public["run_id"], claim["claim_token"])
