"""Offline runs remain synthetic, owner-scoped and disjoint from native/physical gates."""

from uuid import uuid4

import pytest
from academy.mock_connector import advance_mock, run_mock
from academy.models import Action, Experiment


def plan(instrument="flex"):
    return Experiment(
        course_id="workflow-sandbox",
        instrument=instrument,
        layout={"tips": "B1", "stock": "D1", "plate": "D2", "waste": "D3"}
        if instrument == "flex"
        else {"tips": "1", "stock": "2", "plate": "3", "waste": "12"},
        diluent_volume=0,
        actions=[
            Action(kind="pickup"),
            Action(kind="aspirate"),
            Action(kind="dispense", well="A1"),
            Action(kind="drop"),
        ],
    )


def prepare(client):
    saved = client.post("/api/sessions", json=plan().model_dump(mode="json"))
    assert saved.status_code == 201, saved.text
    session = saved.json()
    payload = {
        "run_id": str(uuid4()),
        "session_id": session["id"],
        "expected_version": session["version"],
    }
    response = client.post("/api/connector-mock/runs", json=payload)
    assert response.status_code == 200, response.text
    return session, payload, response.json()


@pytest.mark.parametrize("instrument", ["flex", "ot2"])
def test_model_executes_steps_over_shared_offline_logic(instrument):
    result = run_mock(plan(instrument))
    assert result["simulation"]["status"] == "completed"
    assert result["simulation"]["state"]["wells"]["A1"]["volume"] == 100
    assert len(result["trace"]) == 4
    assert result["simulation_mode"] is True and result["physical_execution"] is False
    assert result["evidence"] == "synthetic"
    reset = advance_mock(result, "reset")
    assert reset["simulation"]["status"] == "draft" and reset["trace"] == []


def test_fault_stops_without_finishing_or_claiming_success():
    p = plan()
    p.actions = [Action(kind="aspirate")]
    result = run_mock(p)
    assert result["simulation"]["status"] == "faulted"
    assert result["simulation"]["cursor"] == 0
    assert result["simulation"]["events"][-1]["code"] == "no_tip"


def test_versioned_run_refresh_reset_and_source_immutability(client, app):
    session, payload, run = prepare(client)
    url = "/api/connector-mock/runs/" + run["run_id"]
    assert client.post("/api/connector-mock/runs", json=payload).json() == run
    assert (
        client.post(
            "/api/connector-mock/runs", json={**payload, "expected_version": 999}
        ).status_code
        == 409
    )
    step = client.post(url + "/commands", json={"expected_version": 1, "command": "step"}).json()
    assert step["simulation"]["state"]["pipette"]["tip"] is True
    assert (
        client.post(url + "/commands", json={"expected_version": 1, "command": "run"}).status_code
        == 409
    )
    result = client.post(url + "/commands", json={"expected_version": 2, "command": "run"}).json()
    assert result["simulation"]["status"] == "completed"
    assert client.get(url).json() == result
    assert client.get("/api/sessions/" + session["id"]).json()["version"] == session["version"]
    assert (
        client.post(url + "/commands", json={"expected_version": 3, "command": "reset"}).json()[
            "simulation"
        ]["cursor"]
        == 0
    )
    assert app.state.store.get("system#gpu", "host") is None
    assert app.state.store.partition("system#connector-runs") == []
    assert app.state.store.partition("system#runs") == []


def test_other_owner_cannot_access_or_issue_commands(client):
    session, payload, run = prepare(client)
    client.post("/api/auth/guest", json={"name": "Other learner"})
    assert client.get("/api/connector-mock/runs/" + run["run_id"]).status_code == 404
    assert (
        client.post(
            "/api/connector-mock/runs/" + run["run_id"] + "/commands",
            json={"expected_version": 1, "command": "run"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/connector-mock/runs", json={**payload, "run_id": str(uuid4())}
        ).status_code
        == 404
    )


def test_stale_saved_version_and_unsupported_actions_rejected(client):
    session, payload, run = prepare(client)
    assert (
        client.post(
            "/api/connector-mock/runs",
            json={**payload, "run_id": str(uuid4()), "expected_version": 999},
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/connector-mock/runs/" + run["run_id"] + "/commands",
            json={"expected_version": 1, "command": "StartRealMode"},
        ).status_code
        == 422
    )
