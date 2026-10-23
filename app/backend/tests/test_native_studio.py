"""Studio dispatch/media contract tests; fixtures are not GPU acceptance evidence."""

from copy import deepcopy
from uuid import uuid4

import pytest
from academy.media import MediaService
from academy.models import OT2_SLOTS, SLOTS, Action, Experiment
from academy.native_studio import StudioCapability, studio_preflight, studio_scene
from academy.remote_run import (
    RemoteRunRequest,
    RemoteRunSnapshot,
    check_run_snapshot,
    workflow_digest,
)
from academy.runs import WORKERS, BindRequest, RunService, StartRequest, SubmitRun
from academy.store import Conflict
from academy.teaching import new_session
from academy.worker_admin import QUALIFICATION_CHECKS, qualification_changes
from fastapi import HTTPException
from pydantic import ValidationError
from test_dispatch import worker
from test_media import Transport
from test_remote_run import report


def capability(instrument="flex", **changes):
    waste = "D3" if instrument == "flex" else "12"
    slots = sorted((SLOTS - {"A3"} if instrument == "flex" else OT2_SLOTS) - {waste})
    return StudioCapability.model_validate(
        {
            "scene": f"workflow-studio-{instrument}",
            "instrument": instrument,
            "slots": {**{name: slots for name in ("stock", "plate", "tips")}, "waste": [waste]},
            "wells": ["A1", "A2", "A3"],
            "volume_ul": {"min": 1, "max": 300},
            "max_initial_ul": 1500,
            "pipette_capacity_ul": 300,
            "max_steps": 64,
            "max_tips": 16,
            "observed": ["liquid_volume", "tip_state"],
            "viewport": True,
            **changes,
        }
    )


def design(instrument="flex", volume=100):
    return Experiment(
        course_id="workflow-sandbox",
        instrument=instrument,
        diluent_volume=0,
        layout={"tips": "B1", "stock": "D1", "plate": "D2", "waste": "D3"}
        if instrument == "flex"
        else {"tips": "4", "stock": "1", "plate": "2", "waste": "12"},
        actions=[
            Action(kind="pickup"),
            Action(kind="aspirate", well="stock", volume=volume),
            Action(kind="dispense", well="A1", volume=volume),
            Action(kind="drop"),
        ],
    )


def setup(store, instrument="flex", **worker_changes):
    plan = design(instrument)
    scene = studio_scene(plan)
    worker(
        store,
        scenes=[scene],
        capabilities={scene: capability(instrument).model_dump()},
        **worker_changes,
    )
    session = new_session(plan)
    store.put("alice", "session#" + session["id"], session, None)
    return RunService(store, enabled=True), session


def test_saved_layout_amounts_order_and_instrument_bound_without_changes():
    instrument = "flex"
    plan = design(instrument)
    before = plan.model_dump()
    assert studio_preflight(plan, capability(instrument)) == []
    assert plan.model_dump() == before
    changed = plan.model_copy(deep=True)
    changed.actions[1].volume = changed.actions[2].volume = 50
    assert workflow_digest(plan) != workflow_digest(changed)
    changed.layout["tips"], changed.layout["stock"] = (
        changed.layout["stock"],
        changed.layout["tips"],
    )
    assert studio_preflight(changed, capability(instrument)) == []


@pytest.mark.parametrize(
    "mutation,code",
    [
        (lambda p: p.actions.clear(), "length"),
        (lambda p: p.actions.pop(0), "sequence"),
        (lambda p: setattr(p, "source_volume", 0), "source"),
        (lambda p: setattr(p.actions[1], "volume", 301), "capacity"),
        (lambda p: setattr(p.actions[2], "volume", 101), "sequence"),
        (lambda p: p.actions.insert(1, Action(kind="pickup")), "sequence"),
    ],
)
def test_invalid_native_sequences_never_become_execution(mutation, code):
    plan = design()
    mutation(plan)
    assert code in {issue.code for issue in studio_preflight(plan, capability())}


def test_capabilities_are_instrument_specific_and_preflight_covers_layout_ranges():
    plan = design()
    cap = capability(
        slots={"tips": ["A1"], "stock": ["D1"], "plate": ["D2"], "waste": ["D3"]},
        wells=["A2"],
        volume_ul={"min": 1, "max": 50},
    )
    assert {i.code for i in studio_preflight(plan, cap)} == {"slot", "well", "volume"}
    assert studio_preflight(plan, capability("ot2"))[0].code == "instrument"
    for changes in [
        {"scene": "workflow-studio-ot2"},
        {"pipette_capacity_ul": 50},
        {"slots": {"waste": ["D3"]}},
    ]:
        with pytest.raises(ValidationError):
            capability(**changes)


def test_pinned_flex_cad_slot_cannot_be_advertised_or_marked_ready(store):
    declared = capability().model_dump()
    declared["slots"]["tips"].append("A3")
    with pytest.raises(ValidationError):
        StudioCapability.model_validate(declared)
    service, session = setup(store)
    plan = design()
    plan.layout["tips"] = "A3"
    session["experiment"] = plan.model_dump(mode="json")
    store.put("alice", "session#" + session["id"], {**session, "version": 2}, 1)
    result = service.studio_preflight("alice", session["id"])
    assert not result["ready"] and "slot" in {issue["code"] for issue in result["issues"]}
    # A stale or manually corrupted capability still fails closed on every read.
    current = store.get(WORKERS, "lab-1")
    store.put(
        WORKERS,
        "lab-1",
        {
            **current,
            "version": current["version"] + 1,
            "capabilities": {"workflow-studio-flex": declared},
        },
        current["version"],
    )
    assert not service.studio_preflight("alice", session["id"])["ready"]


def test_ot2_declaration_cannot_enable_the_flex_runtime_profile(store):
    plan = design("ot2")
    assert {issue.code for issue in studio_preflight(plan, capability("ot2"))} == {"profile"}
    service, session = setup(store, instrument="ot2")
    assert not service.studio_preflight("alice", session["id"])["ready"]
    with pytest.raises(HTTPException):
        service.submit(
            "alice", SubmitRun(run_id=uuid4(), session_id=session["id"], expected_version=1)
        )


def test_preflight_is_read_only_scoped_and_fails_closed(store):
    service, session = setup(store)
    before = deepcopy(store.get("alice", "session#" + session["id"]))
    report = service.studio_preflight("alice", session["id"])
    assert report["ready"] and report["session_version"] == 1
    assert report["plan_hash"] == workflow_digest(design())
    assert store.get("alice", "session#" + session["id"]) == before
    with pytest.raises(HTTPException) as error:
        service.studio_preflight("bob", session["id"])
    assert error.value.status_code == 404
    service.enabled = False
    assert not service.studio_preflight("alice", session["id"])["ready"]


@pytest.mark.parametrize(
    "changes",
    [{"qualified": False}, {"revoked": True}, {"credential_expires": 1}, {"state": "quarantined"}],
)
def test_inactive_worker_never_makes_studio_ready(store, changes):
    service, session = setup(store, **changes)
    assert not service.studio_preflight("alice", session["id"])["ready"]
    with pytest.raises(HTTPException):
        service.submit(
            "alice", SubmitRun(run_id=uuid4(), session_id=session["id"], expected_version=1)
        )


def test_native_submit_uses_saved_plan_and_claim_rechecks_matching_scene(store):
    service, session = setup(store)
    request = SubmitRun(run_id=uuid4(), session_id=session["id"], expected_version=1)
    result = service.submit("alice", request)
    assert result["scene"] == "workflow-studio-flex"
    assert service.submit("alice", request) == result
    assert not service.studio_preflight("alice", session["id"])["ready"]
    worker(
        store,
        "other",
        scenes=["workflow-studio-ot2"],
        capabilities={"workflow-studio-ot2": capability("ot2").model_dump()},
    )
    assert service.claim("other") is None
    claimed = service.claim("lab-1")
    assert claimed["plan"] == session["experiment"]
    assert claimed["plan_hash"] == workflow_digest(design())
    with pytest.raises(Conflict):
        service.submit(
            "alice", SubmitRun(run_id=uuid4(), session_id=session["id"], expected_version=1)
        )


def test_changed_capability_after_preflight_cannot_dispatch(store):
    service, session = setup(store)
    assert service.studio_preflight("alice", session["id"])["ready"]
    registered = store.get(WORKERS, "lab-1")
    registered["capabilities"]["workflow-studio-flex"]["viewport"] = False
    registered["version"] += 1
    store.put(WORKERS, "lab-1", registered, registered["version"] - 1)
    with pytest.raises(HTTPException):
        service.submit(
            "alice", SubmitRun(run_id=uuid4(), session_id=session["id"], expected_version=1)
        )


def test_studio_media_binds_exact_plan_and_denies_other_owner(store):
    service, session = setup(store)
    request = SubmitRun(run_id=uuid4(), session_id=session["id"], expected_version=1)
    service.submit("alice", request)
    run = service.claim("lab-1")
    service.start(
        "lab-1", request.run_id, StartRequest(claim_token=run["claim_token"], command_id=uuid4())
    )
    service.bind(
        "lab-1",
        request.run_id,
        BindRequest(
            claim_token=run["claim_token"],
            native_session_id=uuid4(),
            expected_revision=1,
            engine_version="fixture-engine",
            asset_version="fixture-assets",
        ),
    )
    transport = Transport()
    media = MediaService(service, transport)
    publisher = media.publisher("lab-1", request.run_id, run["claim_token"])
    viewer = media.viewer("alice", request.run_id, uuid4())
    assert publisher["plan_hash"] == viewer["plan_hash"] == workflow_digest(design())
    with pytest.raises(HTTPException):
        media.viewer("bob", request.run_id, uuid4())
    assert len(transport.grants) == 2


def test_qualification_requires_independent_native_evidence_for_each_instrument():
    old = {"worker_id": "lab-1", "engine_version": "e", "asset_version": "a"}
    scene = "workflow-studio-flex"
    evidence = {
        **old,
        "evidence": "native",
        "checks": dict.fromkeys(QUALIFICATION_CHECKS, True),
        "report_uri": "s3://fixture/report",
        "scenes": [scene],
        "capabilities": {scene: capability().model_dump()},
    }
    with pytest.raises(ValueError):
        qualification_changes(old, evidence)
    evidence["studio_and_media_verified"] = {scene: True}
    assert qualification_changes(old, evidence)["scenes"] == [scene]
    evidence["scenes"].append("workflow-studio-ot2")
    evidence["studio_and_media_verified"]["workflow-studio-ot2"] = True
    evidence["capabilities"]["workflow-studio-ot2"] = capability("ot2").model_dump()
    with pytest.raises(ValueError):
        qualification_changes(old, evidence)


def test_preflight_http_owner_boundary_and_empty_design(client):
    session = client.post("/api/sessions", json=design().model_dump(mode="json")).json()
    response = client.get(f"/api/sessions/{session['id']}/native-preflight")
    assert response.status_code == 200
    assert response.json()["ready"] is False
    assert response.json()["session_version"] == session["version"]
    assert client.get(f"/api/sessions/{uuid4()}/native-preflight").status_code == 404


def native_report(plan=None):
    plan = plan or design()
    request = RemoteRunRequest(
        run_id=uuid4(), expected_revision=1, experiment=plan, plan_hash=workflow_digest(plan)
    )
    native_id = uuid4()
    body = report(native_id, request, completed=len(plan.actions))
    body["native_state"].update(
        tip_attached=False,
        pipette_volume_ul=0,
        well_volumes_ul={"stock": 900, "A1": 100, "A2": 0, "A3": 0},
        studio={
            "scene": studio_scene(plan),
            "instrument": plan.instrument,
            "labware_slots": plan.layout,
            "observation_model": "native-semantic",
            "waste_volume_ul": 0,
            "native_action_index": 16,
            "native_action_count": 16,
            "native_action": "Workflow finished",
        },
    )
    return native_id, request, body


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "layout",
        "instrument",
        "lost_liquid",
        "wrong_volume",
        "motion_unfinished",
        "tip",
        "unobserved",
    ],
)
def test_studio_native_completion_rejects_unbound_or_inconsistent_observations(fault):
    native_id, request, body = native_report()
    check_run_snapshot(RemoteRunSnapshot.model_validate(body), native_id, request)
    state = body["native_state"]
    if fault == "missing":
        state["studio"] = None
    elif fault == "layout":
        state["studio"]["labware_slots"] = {**state["studio"]["labware_slots"], "tips": "A1"}
    elif fault == "instrument":
        state["studio"].update(scene="workflow-studio-ot2", instrument="ot2")
    elif fault == "lost_liquid":
        state["well_volumes_ul"]["stock"] -= 1
    elif fault == "wrong_volume":
        state["well_volumes_ul"].update(stock=950, A1=50)
    elif fault == "motion_unfinished":
        state["studio"]["native_action_index"] -= 1
    elif fault == "tip":
        state["tip_attached"] = True
    elif fault == "unobserved":
        state["well_volumes_ul"]["stock"] = None
    with pytest.raises(ValueError):
        check_run_snapshot(RemoteRunSnapshot.model_validate(body), native_id, request)


@pytest.mark.parametrize("drop", [False, True])
def test_exact_final_held_tip_or_discarded_residue_is_preserved(drop):
    plan = design()
    plan.actions = plan.actions[:2] + ([Action(kind="drop")] if drop else [])
    assert studio_preflight(plan, capability()) == []
    native_id, request, body = native_report(plan)
    state = body["native_state"]
    state.update(tip_attached=not drop, pipette_volume_ul=0 if drop else 100)
    state["well_volumes_ul"]["A1"] = 0
    state["studio"]["waste_volume_ul"] = 100 if drop else 0
    check_run_snapshot(RemoteRunSnapshot.model_validate(body), native_id, request)


@pytest.mark.parametrize(
    "finished,tip,stock,target,attached",
    [
        (0, 0, 1000, 0, False),
        (0, 0, 1000, 0, True),
        (1, 40, 960, 0, True),
        (2, 60, 900, 40, True),
        (3, 0, 900, 100, True),
        (3, 0, 900, 100, False),
    ],
)
def test_only_next_action_can_progress_after_confirmed_prefix(
    finished, tip, stock, target, attached
):
    native_id, request, final = native_report()
    body = report(native_id, request, completed=finished)
    body["native_state"] = final["native_state"]
    body["native_state"].update(
        pipette_volume_ul=tip,
        tip_attached=attached,
        well_volumes_ul={"stock": stock, "A1": target, "A2": 0, "A3": 0},
    )
    check_run_snapshot(RemoteRunSnapshot.model_validate(body), native_id, request)
    body["native_state"]["well_volumes_ul"]["A2"] += 10
    body["native_state"]["well_volumes_ul"]["stock"] -= 10
    with pytest.raises(ValueError, match="prefix"):
        check_run_snapshot(RemoteRunSnapshot.model_validate(body), native_id, request)


def test_initial_amounts_cannot_confirm_transfers_even_before_final_status():
    native_id, request, final = native_report()
    body = report(native_id, request, completed=3)
    body["native_state"] = final["native_state"]
    body["native_state"]["well_volumes_ul"].update(stock=1000, A1=0)
    with pytest.raises(ValueError, match="prefix"):
        check_run_snapshot(RemoteRunSnapshot.model_validate(body), native_id, request)
