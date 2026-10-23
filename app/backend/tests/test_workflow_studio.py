"""Free designs use persisted synthetic bookkeeping, never native qualification."""

import hashlib
import json
from copy import deepcopy
from uuid import uuid4

import pytest
from academy.auth import local_signer
from academy.models import DEFAULT_LAYOUT, Experiment
from academy.remote_run import RemoteRunRequest, workflow_digest
from academy.runs import QUEUE, RUNS
from academy.teaching import assessment, initial_state
from fastapi.testclient import TestClient

OT2_LAYOUT = {"stock": "1", "plate": "2", "tips": "5", "waste": "12"}


def design(instrument="flex", **changes):
    return {
        "course_id": "workflow-sandbox",
        "instrument": instrument,
        "title": "My own split transfer",
        "layout": dict(DEFAULT_LAYOUT if instrument == "flex" else OT2_LAYOUT),
        "source_volume": 250,
        "diluent_volume": 0,
        "actions": [
            {"kind": "pickup"},
            {"kind": "aspirate", "well": "stock", "volume": 150},
            {"kind": "dispense", "well": "A2", "volume": 40},
            {"kind": "dispense", "well": "A3", "volume": 110},
            {"kind": "drop"},
        ],
        **changes,
    }


def create(client, payload):
    response = client.post("/api/sessions", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def command(client, session, verb):
    response = client.post(
        f"/api/sessions/{session['id']}/{verb}", json={"version": session["version"]}
    )
    assert response.status_code == 200, response.text
    return response.json()


def finish(client, session):
    session = command(client, session, "start")
    while session["status"] == "running":
        session = command(client, session, "advance")
    return session


@pytest.mark.parametrize("instrument", ["flex", "ot2"])
def test_custom_non_dilution_runs_save_reconnect_reset_and_run_again(client, app, instrument):
    session = create(client, design(instrument))
    path = f"/api/sessions/{session['id']}"
    changed = {**session["experiment"], "title": "Split 150 µL between two wells"}
    saved = client.put(path, json={"version": 1, "experiment": changed})
    assert saved.status_code == 200
    session = saved.json()
    assert session["version"] == 2
    assert session["experiment"]["instrument"] == instrument

    with TestClient(app) as reconnect:
        reconnect.cookies.update(client.cookies)
        assert reconnect.get(path).json() == session
        running = command(reconnect, session, "start")
        running = command(reconnect, running, "advance")
        running = command(reconnect, running, "advance")
        assert running["state"]["pipette"]["volume"] == 150
    assert client.get(path).json() == running
    session = running
    while session["status"] == "running":
        session = command(client, session, "advance")
    assert session["status"] == "completed"
    assert session["evidence"] == "synthetic"
    assert session["engine"] == "teaching"
    assert session["assessment"]["scope"] == "model-checks"
    assert session["assessment"]["passed"]
    assert session["assessment"]["concentrations"] == {"A1": 0, "A2": 100, "A3": 100}
    assert "target_concentrations" not in session["assessment"]
    assert all("reaches" not in check["label"] for check in session["assessment"]["checks"])
    first = deepcopy(session)

    reset = command(client, session, "reset")
    assert reset["state"] == initial_state(reset["experiment"])
    assert reset["experiment"] == first["experiment"]
    assert reset["attempts"][-1]["assessment"] == first["assessment"]
    assert reset["assessment"] is None
    second = finish(client, reset)
    assert second["state"] == first["state"]
    assert second["assessment"] == first["assessment"]
    assert second["version"] > first["version"]
    assert client.get(path).json() == second


@pytest.mark.parametrize("instrument", ["flex", "ot2"])
def test_blank_design_can_be_saved_but_needs_a_step_to_run(client, instrument):
    session = create(client, design(instrument, actions=[]))
    path = f"/api/sessions/{session['id']}"
    response = client.post(path + "/start", json={"version": session["version"]})
    assert response.status_code == 409
    assert response.json()["detail"] == "Add a step before running your workflow"
    assert client.get(path).json() == session


@pytest.mark.parametrize("instrument", ["flex", "ot2"])
def test_tip_only_experiment_is_valid_without_inventing_a_liquid_goal(client, instrument):
    session = finish(
        client, create(client, design(instrument, actions=[{"kind": "pickup"}, {"kind": "drop"}]))
    )
    assert session["assessment"]["passed"]
    assert session["assessment"]["scope"] == "model-checks"
    assert session["state"]["wells"] == initial_state(session["experiment"])["wells"]


@pytest.mark.parametrize("instrument", ["flex", "ot2"])
def test_discarded_liquid_remains_accounted_for_in_model_checks(client, instrument):
    session = finish(
        client,
        create(
            client,
            design(
                instrument,
                actions=[
                    {"kind": "pickup"},
                    {"kind": "aspirate", "well": "stock", "volume": 80},
                    {"kind": "dispense", "well": "A1", "volume": 30},
                    {"kind": "drop"},
                ],
            ),
        ),
    )
    assert session["state"]["waste_volume"] == 50
    assert session["state"]["waste_solute"] == 5000
    assert session["assessment"]["passed"]


@pytest.mark.parametrize("instrument", ["flex", "ot2"])
def test_unfinished_pipette_state_does_not_pass_model_checks(client, instrument):
    session = finish(client, create(client, design(instrument, actions=[{"kind": "pickup"}])))
    assert session["status"] == "completed"
    assert not session["assessment"]["passed"]
    assert not session["assessment"]["checks"][-1]["passed"]


@pytest.mark.parametrize(
    ("instrument", "layout"),
    [
        ("flex", {**DEFAULT_LAYOUT, "stock": "1"}),
        ("flex", {**DEFAULT_LAYOUT, "waste": "C3"}),
        ("flex", {**DEFAULT_LAYOUT, "tips": "D1"}),
        ("flex", {key: value for key, value in DEFAULT_LAYOUT.items() if key != "plate"}),
        ("ot2", DEFAULT_LAYOUT),
        ("ot2", {**OT2_LAYOUT, "stock": "A1"}),
        ("ot2", {**OT2_LAYOUT, "waste": "11"}),
        ("ot2", {**OT2_LAYOUT, "tips": "1"}),
        ("ot2", {**OT2_LAYOUT, "plate": "12"}),
        ("ot2", {key: value for key, value in OT2_LAYOUT.items() if key != "plate"}),
        ("ot2", {**OT2_LAYOUT, "extra": "3"}),
    ],
)
def test_instrument_deck_validation_has_no_saved_side_effects(client, instrument, layout):
    response = client.post("/api/sessions", json=design(instrument, layout=layout))
    assert response.status_code == 422
    assert client.get("/api/sessions").json() == []


def test_ot2_requires_explicit_numbered_layout_and_existing_lessons_stay_flex(client):
    payload = design("ot2")
    payload.pop("layout")
    assert client.post("/api/sessions", json=payload).status_code == 422
    for course in ["flex-foundations", "flex-first-transfer"]:
        assert client.post("/api/sessions", json=design("ot2", course_id=course)).status_code == 422
        assert (
            client.post("/api/sessions", json={"course_id": course, "actions": []}).status_code
            == 422
        )
    assert Experiment().instrument == "flex"
    assert Experiment().layout == DEFAULT_LAYOUT


@pytest.mark.parametrize("instrument", ["flex", "ot2"])
@pytest.mark.parametrize(
    ("actions", "changes", "code"),
    [
        ([{"kind": "aspirate"}], {}, "no_tip"),
        ([{"kind": "pickup"}, {"kind": "aspirate", "volume": 301}], {}, "capacity"),
        ([{"kind": "pickup"}, {"kind": "aspirate", "volume": 251}], {}, "source_empty"),
        (
            [
                {"kind": "pickup"},
                {"kind": "aspirate", "volume": 100},
                {"kind": "dispense", "well": "A1", "volume": 100},
            ],
            {"diluent_volume": 1450},
            "overflow",
        ),
    ],
)
def test_faulting_block_preserves_liquids_and_cursor(client, instrument, actions, changes, code):
    session = command(
        client, create(client, design(instrument, actions=actions, **changes)), "start"
    )
    while session["status"] == "running":
        before = session
        session = command(client, session, "advance")
    assert session["status"] == "faulted"
    assert session["state"] == before["state"]
    assert session["cursor"] == before["cursor"]
    assert session["events"][-1]["code"] == code
    assert session["assessment"] is None


@pytest.mark.parametrize("instrument", ["flex", "ot2"])
def test_stale_save_and_instrument_change_cannot_replace_design(client, instrument):
    session = create(client, design(instrument))
    path = f"/api/sessions/{session['id']}"
    saved = client.put(
        path, json={"version": 1, "experiment": {**session["experiment"], "title": "Saved design"}}
    ).json()
    assert saved["version"] == 2
    assert (
        client.put(path, json={"version": 1, "experiment": session["experiment"]}).status_code
        == 409
    )
    other = "ot2" if instrument == "flex" else "flex"
    response = client.put(path, json={"version": 2, "experiment": design(other)})
    assert response.status_code == 409
    assert "change instruments" in response.json()["detail"]
    assert client.get(path).json() == saved


def test_legacy_session_without_instrument_remains_flex_and_can_run(client, app):
    session = create(client, {})
    owner = local_signer(app.state.settings).loads(client.cookies.get("academy_local"))["sub"]
    session["experiment"].pop("instrument", None)
    session["version"] += 1
    app.state.store.put(owner, f"session#{session['id']}", session, 1)
    loaded = client.get(f"/api/sessions/{session['id']}").json()
    saved = client.put(
        f"/api/sessions/{session['id']}",
        json={"version": loaded["version"], "experiment": loaded["experiment"]},
    ).json()
    assert saved["experiment"].get("instrument", "flex") == "flex"
    assert "instrument" not in saved["experiment"]
    finished = finish(client, saved)
    assert finished["assessment"]["passed"]
    assert "scope" not in finished["assessment"]


@pytest.mark.parametrize("instrument", ["flex", "ot2"])
def test_designs_are_isolated_between_learners(client, app, instrument):
    session = create(client, design(instrument))
    path = f"/api/sessions/{session['id']}"
    with TestClient(app) as other:
        assert other.post("/api/auth/guest", json={"name": "Another learner"}).status_code == 200
        assert other.get(path).status_code == 404
        assert (
            other.put(path, json={"version": 1, "experiment": session["experiment"]}).status_code
            == 404
        )
        for verb in ["start", "advance", "reset"]:
            assert other.post(path + "/" + verb, json={"version": 1}).status_code == 404
        assert other.get("/api/sessions").json() == []
    assert client.get(path).json() == session


@pytest.mark.parametrize("instrument", ["flex", "ot2"])
def test_sandbox_is_rejected_without_qualified_studio_host_even_when_remote_is_enabled(
    client, app, instrument
):
    app.state.runs.enabled = True
    session = create(client, design(instrument))
    run_id = str(uuid4())
    response = client.post(
        "/api/runs",
        json={
            "run_id": run_id,
            "session_id": session["id"],
            "expected_version": session["version"],
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["issues"][0]["code"] == "host"
    assert app.state.store.get(RUNS, run_id) is None
    assert app.state.store.get(QUEUE, run_id) is None
    assert client.get(f"/api/sessions/{session['id']}/remote-run").json() is None
    assert client.get(f"/api/sessions/{session['id']}").json() == session


@pytest.mark.parametrize(
    "fault", ["volume_lost", "tracer_lost", "negative", "over_capacity", "infinite", "unfinished"]
)
def test_model_checks_detect_corrupted_bookkeeping_and_unfinished_steps(fault):
    experiment = Experiment(**design(actions=[{"kind": "pickup"}, {"kind": "drop"}])).model_dump()
    state = initial_state(experiment)
    completed_steps = 2
    if fault == "volume_lost":
        state["wells"]["stock"]["volume"] -= 1
    elif fault == "tracer_lost":
        state["wells"]["stock"]["solute"] -= 1
    elif fault == "negative":
        state["wells"]["A1"]["volume"] = -1
        state["wells"]["stock"]["volume"] += 1
    elif fault == "over_capacity":
        state["wells"]["stock"]["volume"] = 1501
    elif fault == "infinite":
        state["waste_solute"] = float("inf")
    elif fault == "unfinished":
        completed_steps = 1
    assert not assessment(state, experiment, completed_steps)["passed"]


def test_course_catalog_explains_studio_model_without_native_claims(client):
    course = next(
        course for course in client.get("/api/courses").json() if course["id"] == "workflow-sandbox"
    )
    assert course["title"] == "Workflow Studio"
    assert "300 µL" in course["model_note"]
    assert "Synthetic" in course["model_note"]
    assert "target_concentrations" not in course


@pytest.mark.parametrize("course_id", ["flex-foundations", "flex-first-transfer"])
def test_fixed_flex_courses_preserve_legacy_wire_definition_and_native_digest(course_id):
    pairs = [("stock", "A1"), ("A1", "A2"), ("A2", "A3")]
    if course_id == "flex-first-transfer":
        pairs = pairs[:1]
    actions = [
        action
        for source, target in pairs
        for action in [
            {"kind": "pickup", "well": "stock", "volume": 100},
            {"kind": "aspirate", "well": source, "volume": 100},
            {"kind": "dispense", "well": target, "volume": 100},
            {"kind": "drop", "well": "stock", "volume": 100},
        ]
    ]
    legacy = {
        "title": "My serial dilution",
        "course_id": course_id,
        "transfer_volume": 100.0,
        "layout": {"stock": "D1", "plate": "D2", "tips": "B1", "waste": "D3"},
        "source_volume": 1000.0,
        "diluent_volume": 0.0 if course_id == "flex-first-transfer" else 100.0,
        "actions": [{**action, "volume": 100.0} for action in actions],
    }
    legacy_hash = hashlib.sha256(
        json.dumps(legacy, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    for data in [legacy, {**legacy, "instrument": "flex"}]:
        plan = Experiment.model_validate(data)
        assert plan.instrument == "flex"
        assert plan.model_dump(mode="json") == legacy
        assert workflow_digest(plan) == legacy_hash
        request = RemoteRunRequest(
            run_id=uuid4(), expected_revision=1, experiment=plan, plan_hash=legacy_hash
        )
        assert request.model_dump(mode="json")["experiment"] == legacy
        assert RemoteRunRequest.model_validate(request.model_dump(mode="json")) == request


def test_sandbox_instrument_is_part_of_persisted_definition_and_digest():
    for instrument in ["flex", "ot2"]:
        plan = Experiment(**design(instrument))
        payload = plan.model_dump(mode="json")
        assert payload["instrument"] == instrument
        without_instrument = {key: value for key, value in payload.items() if key != "instrument"}
        unbound_hash = hashlib.sha256(
            json.dumps(without_instrument, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        assert workflow_digest(plan) != unbound_hash
