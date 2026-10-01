"""Synthetic contract fixtures only: these tests do not qualify a GPU runtime."""

from copy import deepcopy
from uuid import uuid4

import pytest
from academy.recipes import CreateMixing, MixingPlan, mixing_session, mixing_steps
from academy.remote_run import (
    RemoteRunRequest,
    RemoteRunSnapshot,
    check_run_snapshot,
    workflow_digest,
)
from academy.runs import RunService, SubmitRun
from pydantic import ValidationError
from test_dispatch import worker
from test_remote_run import report


def mixing_report(completed=5):
    plan = MixingPlan()
    request = RemoteRunRequest(
        run_id=uuid4(), expected_revision=1, experiment=plan, plan_hash=workflow_digest(plan)
    )
    session = uuid4()
    body = report(session, request, completed=completed, sequence=1)
    sources = [s.source_index for s in plan.actions[1:]]
    amounts = [10 if i in sources[: max(0, completed - 1)] else 0 for i in range(8)]
    tips = [f"Tips__A{i}" for i in range(1, max(0, completed - 1) + 1)]
    body["native_state"].update(
        pipette_volume_ul=0,
        tip_attached=False,
        well_volumes_ul={"stock": None, "A1": sum(amounts), "A2": None, "A3": None},
        mixing=dict(
            source_volumes_ul=[1500 - v for v in amounts],
            mixture_components_ul=amounts,
            source_order=sources,
            lid_parked=completed > 0,
            lid_attached=False,
            active_tip=None,
            tips_used=tips,
            tips_discarded=tips,
            joint_positions=[0] * 7,
            native_action_index=86 if completed == 5 else 0,
            native_action_count=86,
            native_action="Synthetic fixture",
        ),
    )
    return session, request, body


def test_seed_actions_are_pinned_and_cannot_be_replaced_with_teaching_plan():
    assert [s.source_index for s in MixingPlan().actions[1:]] == [1, 0, 5, 2]
    assert MixingPlan(seed=19, actions=mixing_steps(19)).seed == 19
    for change in [{"seed": 19}, {"num_envs": 2}, {"task": "Matterix-Pour-v1"}, {"seed": True}]:
        with pytest.raises(ValidationError):
            MixingPlan.model_validate(MixingPlan().model_dump() | change)


def test_native_sessions_are_owned_idempotent_and_do_not_enter_the_teaching_engine(client):
    request = {"session_id": str(uuid4()), "seed": 42}
    first = client.post("/api/simulations", json=request)
    assert first.status_code == 201
    assert first.json()["state"] is None
    assert client.post("/api/simulations", json=request).json() == first.json()
    assert client.get("/api/sessions").json() == []
    assert len(client.get("/api/simulations").json()["sessions"]) == 1
    for verb in ("start", "advance", "reset", "pause", "resume"):
        response = client.post(f"/api/sessions/{request['session_id']}/{verb}", json={"version": 1})
        assert response.status_code in {404, 409}
    client.post("/api/auth/guest", json={"name": "Another learner"})
    assert client.get(f"/api/sessions/{request['session_id']}").status_code == 404
    assert client.get("/api/simulations").json()["sessions"] == []


def test_only_a_scene_qualified_worker_can_claim_mixing(store):
    service = RunService(store, True, clock=lambda: 1790863200)
    session = mixing_session(CreateMixing(session_id=uuid4()))
    store.put("alice", "session#" + session["id"], session, None)
    service.submit("alice", SubmitRun(run_id=uuid4(), session_id=session["id"], expected_version=1))
    worker(store, "legacy")
    assert service.claim("legacy") is None
    worker(store, "mixing", scenes=["flex-mixing"], controls=[])
    assert service.claim("mixing")["plan"]["workflow"] == "mix_four_vials"


def test_matching_native_mixture_is_accepted_but_never_computed_by_api():
    session, request, body = mixing_report()
    check_run_snapshot(RemoteRunSnapshot.model_validate(body), session, request)
    assert request.experiment.num_envs == 1


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "wrong_sources",
        "no_lid",
        "one_tip",
        "wrong_component",
        "wrong_total",
        "source_mass",
        "attached",
        "not_finished",
    ],
)
def test_unobserved_or_inconsistent_mixing_cannot_pass(case):
    session, request, body = mixing_report()
    state = body["native_state"]
    if case == "missing":
        state["mixing"] = None
    if case == "wrong_sources":
        state["mixing"]["source_order"] = [0, 1, 2, 3]
    if case == "no_lid":
        state["mixing"]["lid_parked"] = False
    if case == "one_tip":
        state["mixing"]["tips_discarded"] = ["Tips__A1"]
    if case == "wrong_component":
        state["mixing"]["mixture_components_ul"][1] = 9
    if case == "wrong_total":
        state["well_volumes_ul"]["A1"] = 30
    if case == "source_mass":
        state["mixing"]["source_volumes_ul"][1] = 1500
    if case == "attached":
        state["tip_attached"] = True
    if case == "not_finished":
        state["mixing"]["native_action_index"] = 85
    with pytest.raises(ValueError):
        check_run_snapshot(RemoteRunSnapshot.model_validate(body), session, request)


def test_in_flight_tip_disposal_does_not_falsely_complete_retract():
    session, request, body = mixing_report(1)
    state = body["native_state"]["mixing"]
    state["tips_used"] = ["Tips__A1"]
    state["tips_discarded"] = ["Tips__A1"]
    before = deepcopy(body)
    check_run_snapshot(RemoteRunSnapshot.model_validate(body), session, request)
    assert body == before
    assert RemoteRunSnapshot.model_validate(body).completed_steps == 1
