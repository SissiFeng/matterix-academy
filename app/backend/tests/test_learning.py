from copy import deepcopy

import pytest
from academy.models import DEFAULT_LAYOUT, Experiment
from academy.teaching import new_session
from fastapi.testclient import TestClient


def lesson(volume=100):
    return {
        "course_id": "flex-first-transfer",
        "title": "First transfer",
        "transfer_volume": volume,
        "source_volume": 1000,
        "diluent_volume": 0,
        "actions": [
            {"kind": "pickup"},
            {"kind": "aspirate", "volume": volume},
            {"kind": "dispense", "well": "A1", "volume": volume},
            {"kind": "drop"},
        ],
    }


def create(client, volume=100):
    response = client.post("/api/sessions", json=lesson(volume))
    assert response.status_code == 201, response.text
    return response.json()


def learning(client, session, **patch):
    response = client.put(
        f"/api/sessions/{session['id']}/learning",
        json={
            "version": session["version"],
            "learning": {**session["learning"], **patch},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def ready(client, session):
    volume = session["experiment"]["transfer_volume"]
    return learning(
        client,
        session,
        visited=["pipette", "tips", "stock", "plate", "waste"],
        location_answer="well",
        checks=["instrument", "labware", "liquids", "simulation"],
        prediction={"source": 1000 - volume, "tip": volume, "target": 0},
        phase="run",
    )


def control(client, session, command):
    response = client.post(
        f"/api/sessions/{session['id']}/{command}", json={"version": session["version"]}
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("volume", [50, 100])
def test_first_lesson_requires_understanding_and_records_transfer(client, volume):
    run = create(client, volume)
    assert not run["readiness"]["ready"]
    assert (
        client.post(
            f"/api/sessions/{run['id']}/start", json={"version": run["version"]}
        ).status_code
        == 409
    )
    run = ready(client, run)
    run = learning(client, run, prediction={"source": 1000 - volume, "tip": 0, "target": volume})
    assert not run["readiness"]["ready"]
    assert (
        client.post(
            f"/api/sessions/{run['id']}/start", json={"version": run["version"]}
        ).status_code
        == 409
    )
    run = ready(client, run)
    assert client.get(f"/api/sessions/{run['id']}").json()["learning"] == run["learning"]
    run = control(client, run, "start")
    run = control(client, run, "advance")
    run = control(client, run, "advance")
    assert run["state"]["wells"]["stock"]["volume"] == 1000 - volume
    assert run["state"]["pipette"]["volume"] == volume
    assert run["state"]["wells"]["A1"]["volume"] == 0
    run = control(client, run, "pause")
    run = control(client, run, "resume")
    run = control(client, run, "advance")
    run = control(client, run, "advance")
    assert run["assessment"]["passed"]
    assert run["lesson_outcome"]["practice_completed"]
    assert not run["lesson_outcome"]["understanding_demonstrated"]
    run = learning(client, run, phase="reflect", reflection="source_to_tip")
    assert run["lesson_outcome"]["understanding_demonstrated"]
    assert run["lesson_outcome"]["evidence"] == "synthetic"
    previous = deepcopy(run)
    run = control(client, run, "reset")
    assert run["attempts"][-1]["learning"] == previous["learning"]
    assert not run["readiness"]["ready"]
    assert run["learning"]["prediction"] is None
    assert run["state"]["wells"]["stock"]["volume"] == 1000


def test_edits_invalidate_prediction_and_preflight(client):
    run = ready(client, create(client))
    updated = {**run["experiment"], "layout": {**run["experiment"]["layout"], "tips": "C1"}}
    response = client.put(
        f"/api/sessions/{run['id']}", json={"version": run["version"], "experiment": updated}
    )
    assert response.status_code == 200
    run = response.json()
    assert run["learning"]["prediction"] is None
    assert run["learning"]["checks"] == []
    assert run["learning"]["visited"]
    assert not run["readiness"]["ready"]


def test_resuming_rechecks_learning_after_paused_edits(client):
    run = control(client, ready(client, create(client)), "start")
    run = control(client, run, "pause")
    run = learning(client, run, prediction=None)
    assert (
        client.post(
            f"/api/sessions/{run['id']}/resume", json={"version": run["version"]}
        ).status_code
        == 409
    )
    assert client.get(f"/api/sessions/{run['id']}").json()["status"] == "paused"
    run = ready(client, run)
    assert control(client, run, "resume")["status"] == "running"


def test_learning_is_owned_versioned_and_cannot_change_running_state(client, app):
    run = ready(client, create(client))
    payload = {"version": run["version"], "learning": run["learning"]}
    path = f"/api/sessions/{run['id']}/learning"
    with TestClient(app) as other:
        other.post("/api/auth/guest", json={"name": "Other"})
        assert other.put(path, json=payload).status_code == 404
    run = learning(client, run, phase="predict")
    assert client.put(path, json=payload).status_code == 409
    run = control(client, run, "start")
    assert client.put(path, json={**payload, "version": run["version"]}).status_code == 409


@pytest.mark.parametrize(
    "patch",
    [
        {"layout": {**DEFAULT_LAYOUT, "waste": "A3"}},
        {"actions": [{"kind": "pickup"}, {"kind": "drop"}]},
        {"transfer_volume": 301},
        {"diluent_volume": 100},
    ],
)
def test_first_lesson_rejects_inconsistent_deck_or_plan(client, patch):
    assert client.post("/api/sessions", json={**lesson(), **patch}).status_code == 422


def test_legacy_deck_is_not_silently_moved_and_must_be_corrected(client, app):
    profile = client.get("/api/me").json()
    assert profile["name"] == "Ada"
    run = client.post("/api/sessions", json={}).json()
    # Locate the signed learner subject without changing authorization behavior.
    from academy.auth import local_signer

    owner = local_signer(app.state.settings).loads(client.cookies.get("academy_local"))["sub"]
    legacy = new_session(Experiment())
    legacy.update(id=run["id"], version=run["version"] + 1)
    legacy["experiment"]["layout"]["waste"] = "A3"
    app.state.store.put(owner, f"session#{run['id']}", legacy, run["version"])
    loaded = client.get(f"/api/sessions/{run['id']}").json()
    assert loaded["experiment"]["layout"]["waste"] == "A3"
    assert (
        client.post(
            f"/api/sessions/{run['id']}/start", json={"version": loaded["version"]}
        ).status_code
        == 409
    )


def test_remote_status_is_unavailable_without_operator_configuration(client, app):
    assert client.get("/api/remote/status").json()["state"] == "not_configured"
    assert client.get("/api/remote/status").json()["available"] is False
    with TestClient(app) as anonymous:
        assert anonymous.get("/api/remote/status").status_code == 401
