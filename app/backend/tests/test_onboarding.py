from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


def device_payload(**changes):
    return {
        "expected_version": 0,
        "name": "Flex 01",
        "workcell": "Liquid handling",
        "model": "opentrons_flex",
        "connection": "native_api",
        "capabilities": ["pickup", "aspirate", "dispense", "drop"],
        "stage": 3,
        **changes,
    }


def create_device(client, **changes):
    device_id = str(uuid4())
    response = client.put(f"/api/devices/{device_id}", json=device_payload(**changes))
    assert response.status_code == 200, response.text
    return response.json()


def test_device_progress_is_persistent_versioned_and_not_physical_evidence(client):
    device = create_device(client, connection="", capabilities=[], stage=1)
    path = f"/api/devices/{device['id']}"
    assert client.get(path).json() == device
    assert client.get("/api/devices").json() == [device]
    assert device["evidence"] == "declaration_only"
    assert device["physical_state"] is None
    assert device["physical_ready"] is False
    assert client.put(path, json=device_payload()).status_code == 409
    assert client.post(f"{path}/twin", json={"expected_version": 1}).status_code == 409
    saved = client.put(path, json=device_payload(expected_version=1)).json()
    assert saved["version"] == 2
    assert client.put(path, json=device_payload(expected_version=1)).status_code == 409
    assert client.get(path).json() == saved


def test_twin_creation_is_atomic_and_cannot_be_replayed(client):
    device = create_device(client)
    path = f"/api/devices/{device['id']}/twin"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: client.post(path, json={"expected_version": 1}), range(2))
        )
    assert sorted(result.status_code for result in results) == [200, 409]
    twin = next(result.json() for result in results if result.status_code == 200)
    assert twin["version"] == 2
    assert twin["session"]["id"] == twin["twin_session_id"]
    assert len(client.get("/api/sessions").json()) == 1
    assert client.post(path, json={"expected_version": 2}).status_code == 409
    assert client.get(f"/api/devices/{device['id']}").json() == twin


def test_teaching_progress_never_clears_physical_gates_and_reset_invalidates_it(client):
    device = create_device(client)
    path = f"/api/devices/{device['id']}"
    twin = client.post(f"{path}/twin", json={"expected_version": 1}).json()
    trial_path = f"/api/sessions/{twin['twin_session_id']}"
    session = client.post(f"{trial_path}/start", json={"version": 1}).json()
    while session["status"] == "running":
        session = client.post(f"{trial_path}/advance", json={"version": session["version"]}).json()
    assert session["assessment"]["passed"]
    result = client.get(path).json()
    assert all(c["status"] == "passed" for c in result["checks"] if c["scope"] == "teaching")
    assert all(c["status"] == "missing" for c in result["checks"] if c["scope"] == "physical")
    assert result["physical_ready"] is False
    assert result["session"]["version"] == session["version"]
    client.post(f"{trial_path}/reset", json={"version": session["version"]})
    assert (
        next(c for c in client.get(path).json()["checks"] if c["id"] == "trial")["status"]
        == "missing"
    )
    changed = client.put(
        path, json=device_payload(expected_version=2, capabilities=["image"])
    ).json()
    assert changed["twin_session_id"] == twin["twin_session_id"]
    assert next(c for c in changed["checks"] if c["id"] == "capabilities")["status"] == "failed"


def test_devices_and_bound_sessions_are_owner_scoped(client, app):
    device = create_device(client)
    path = f"/api/devices/{device['id']}"
    with TestClient(app) as other:
        assert other.get("/api/devices").status_code == 401
        assert other.put(path, json=device_payload()).status_code == 401
        assert other.post(f"{path}/twin", json={"expected_version": 1}).status_code == 401
        other.post("/api/auth/guest", json={"name": "Other learner"})
        assert other.get("/api/devices").json() == []
        assert other.get(path).status_code == 404
        assert other.post(f"{path}/twin", json={"expected_version": 1}).status_code == 404
        assert other.put(path, json=device_payload(expected_version=1)).status_code == 409
    assert client.get(path).json() == device


@pytest.mark.parametrize(
    "changes",
    [
        {"name": " "},
        {"workcell": " "},
        {"name": "x" * 81},
        {"expected_version": True},
        {"expected_version": -1},
        {"stage": 4},
        {"stage": 2, "connection": ""},
        {"stage": 3, "capabilities": []},
        {"capabilities": ["aspirate", "aspirate"]},
        {"capabilities": ["shell"]},
        {"physical_ready": True},
        {"twin_session_id": str(uuid4())},
        {"owner": "somebody-else"},
        {"host": "192.168.1.2"},
    ],
)
def test_device_rejects_untrusted_authority_and_invalid_progress(client, changes):
    assert client.put(f"/api/devices/{uuid4()}", json=device_payload(**changes)).status_code == 422
    assert client.get("/api/devices").json() == []
