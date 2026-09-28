from concurrent.futures import ThreadPoolExecutor

import pytest
from academy.models import Experiment
from academy.teaching import initial_state
from fastapi.testclient import TestClient


def mutate(client, session, command):
    response = client.post(
        f"/api/sessions/{session['id']}/{command}", json={"version": session["version"]}
    )
    assert response.status_code == 200, response.text
    return response.json()


def create(client, **changes):
    response = client.post("/api/sessions", json=changes)
    assert response.status_code == 201, response.text
    return response.json()


def total(state, field):
    waste = "waste_volume" if field == "volume" else "waste_solute"
    return (
        sum(well[field] for well in state["wells"].values())
        + state["pipette"][field]
        + state[waste]
    )


def test_complete_dilution_preserves_mass_and_reaches_goal(client):
    session = create(client)
    baseline = session["state"]
    session = mutate(client, session, "start")
    for _ in range(12):
        session = mutate(client, session, "advance")
        assert total(session["state"], "volume") == pytest.approx(total(baseline, "volume"))
        assert total(session["state"], "solute") == pytest.approx(total(baseline, "solute"))
    assert session["status"] == "completed"
    assert session["assessment"]["passed"]
    assert session["assessment"]["concentrations"] == {"A1": 50, "A2": 25, "A3": 12.5}
    assert session["state"]["tips_used"] == session["state"]["tips_discarded"] == 3
    assert session["evidence"] == "synthetic"


@pytest.mark.parametrize(
    ("actions", "changes", "code"),
    [
        ([{"kind": "aspirate"}], {}, "no_tip"),
        ([{"kind": "pickup"}, {"kind": "pickup"}], {}, "tip_attached"),
        ([{"kind": "pickup"}, {"kind": "aspirate", "volume": 301}], {}, "capacity"),
        ([{"kind": "pickup"}, {"kind": "aspirate"}], {"source_volume": 50}, "source_empty"),
        ([{"kind": "pickup"}, {"kind": "dispense"}], {}, "insufficient_liquid"),
        (
            [{"kind": "pickup"}, {"kind": "aspirate"}, {"kind": "dispense", "well": "A1"}],
            {"diluent_volume": 1450},
            "overflow",
        ),
        (
            [
                {"kind": "pickup"},
                {"kind": "aspirate"},
                {"kind": "dispense", "well": "A1"},
                {"kind": "aspirate", "well": "A1"},
            ],
            {},
            "used_tip",
        ),
    ],
)
def test_error_has_cause_without_silently_transferring_liquid(client, actions, changes, code):
    session = create(client, actions=actions, **changes)
    session = mutate(client, session, "start")
    before = None
    while session["status"] == "running":
        before = session["state"]
        session = mutate(client, session, "advance")
    assert session["status"] == "faulted"
    assert session["events"][-1]["code"] == code
    assert session["state"] == before
    assert session["events"][-1]["hint"]
    assert session["assessment"] is None


def test_reset_restores_all_state_and_preserves_attempt_summary(client):
    session = create(client)
    session = mutate(client, session, "start")
    for _ in range(5):
        session = mutate(client, session, "advance")
    old_version = session["version"]
    session = mutate(client, session, "reset")
    assert session["version"] == old_version + 1
    assert session["state"] == initial_state(session["experiment"])
    assert session["events"] == []
    assert session["cursor"] == 0
    assert session["status"] == "draft"
    assert session["attempts"][0]["steps"] == 5


def test_pause_and_stale_requests_cannot_advance(client):
    session = mutate(client, create(client), "start")
    paused = mutate(client, session, "pause")
    for version in [session["version"], paused["version"]]:
        assert (
            client.post(
                f"/api/sessions/{session['id']}/advance", json={"version": version}
            ).status_code
            == 409
        )
    resumed = mutate(client, paused, "resume")
    assert mutate(client, resumed, "advance")["cursor"] == 1


def test_duplicate_mutation_is_applied_only_once(client):
    session = mutate(client, create(client), "start")
    path = f"/api/sessions/{session['id']}/advance"
    data = {"version": session["version"]}
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post(path, json=data), range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    persisted = client.get(f"/api/sessions/{session['id']}").json()
    assert persisted["cursor"] == 1
    assert persisted["state"]["tips_used"] == 1


def test_other_learner_cannot_read_or_mutate_session(client, app):
    session = create(client)
    with TestClient(app) as other:
        other.post("/api/auth/guest", json={"name": "Grace"})
        path = f"/api/sessions/{session['id']}"
        assert other.get(path).status_code == 404
        assert other.post(path + "/start", json={"version": 1}).status_code == 404
        assert (
            other.put(path, json={"version": 1, "experiment": session["experiment"]}).status_code
            == 404
        )
        assert other.get("/api/sessions").json() == []


def test_valid_sequence_does_not_automatically_pass_course(client):
    session = create(client, actions=[{"kind": "pickup"}, {"kind": "drop"}])
    session = mutate(client, session, "start")
    session = mutate(client, session, "advance")
    session = mutate(client, session, "advance")
    assert session["status"] == "completed"
    assert session["assessment"]["passed"] is False


def test_editing_running_session_is_rejected(client):
    session = mutate(client, create(client), "start")
    assert (
        client.put(
            f"/api/sessions/{session['id']}",
            json={"version": session["version"], "experiment": session["experiment"]},
        ).status_code
        == 409
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"source_volume": -1},
        {"actions": []},
        {"actions": [{"kind": "aspirate", "volume": 0}]},
        {"layout": {"stock": "A1", "tips": "A1", "plate": "A2", "waste": "A3"}},
        {"layout": {"stock": "X1", "tips": "B1", "plate": "A2", "waste": "A3"}},
        {"actions": [{"kind": "shell", "command": "ls"}]},
        {"owner": "someone-else"},
    ],
)
def test_invalid_experiment_rejected_at_api(client, payload):
    assert client.post("/api/sessions", json=payload).status_code == 422


def test_nonfinite_volume_rejected():
    with pytest.raises(ValueError):
        Experiment(source_volume=float("nan"))


@pytest.mark.parametrize(
    "kind,code", [("aspirate", "source_empty"), ("dispense", "insufficient_liquid")]
)
def test_tiny_transfer_from_empty_container_reports_fault(client, kind, code):
    session = create(
        client, source_volume=0, actions=[{"kind": "pickup"}, {"kind": kind, "volume": 1e-9}]
    )
    session = mutate(client, session, "start")
    session = mutate(client, session, "advance")
    session = mutate(client, session, "advance")
    assert session["status"] == "faulted"
    assert session["events"][-1]["code"] == code


def test_roundoff_never_creates_negative_liquid(client):
    session = create(
        client,
        source_volume=0.3,
        actions=[
            {"kind": "pickup"},
            {"kind": "aspirate", "volume": 0.3000000001},
            {"kind": "dispense", "well": "A1", "volume": 0.3000000001},
        ],
    )
    baseline = session["state"]
    session = mutate(client, session, "start")
    for _ in range(3):
        session = mutate(client, session, "advance")
    assert session["state"]["wells"]["stock"]["volume"] == 0
    assert session["state"]["pipette"]["volume"] == 0
    assert total(session["state"], "volume") == pytest.approx(total(baseline, "volume"))
    assert total(session["state"], "solute") == pytest.approx(total(baseline, "solute"))


def test_latest_fifty_sessions_are_chronological_not_uuid_sorted(store):
    from academy.teaching import new_session

    created = []
    for index in range(65):
        session = new_session(Experiment(title=f"Attempt {index}"))
        # Deliberately reverse UUID order relative to creation order.
        session["id"] = f"{1000 - index:08d}-0000-0000-0000-000000000000"
        session["created_at"] = f"2026-09-28T10:{index // 60:02d}:{index % 60:02d}+00:00"
        store.put("learner", f"session#{session['id']}", session, None)
        created.append(session["id"])
    assert [s["id"] for s in store.list("learner")] == list(reversed(created))[:50]


def test_state_persists_across_client_reconnect(client, app):
    session = mutate(client, create(client), "start")
    session = mutate(client, session, "advance")
    with TestClient(app) as reconnect:
        reconnect.cookies.update(client.cookies)
        assert reconnect.get(f"/api/sessions/{session['id']}").json() == session
