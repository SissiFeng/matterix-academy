"""The mixing recipe on saved teaching twins: synthetic bookkeeping, never native evidence."""

from uuid import uuid4

import pytest
from academy.mixing_twins import MixingTwinService, TwinRun
from academy.recipes import CreateMixing, mixing_session
from academy.settings import Settings
from academy.simple_twins import TEMPLATES, SimpleTwinService
from fastapi import HTTPException
from test_instruments import add, confirm
from test_onboarding import create_device


def session(client):
    return client.post("/api/simulations", json={"session_id": str(uuid4()), "seed": 42}).json()


def run(client, sim, twin, **changes):
    body = {"run_id": str(uuid4()), "expected_version": sim["version"], "twin": twin, **changes}
    return client.post(f"/api/simulations/{sim['id']}/twin-run", json=body)


def test_a_learner_without_a_gpu_runs_the_recipe_on_the_flex_teaching_twin(client):
    catalog = client.get("/api/simulations").json()
    assert not catalog["enabled"]
    assert catalog["twins"] == [
        {"key": "flex", "kind": "builtin", "name": "Flex teaching twin", "revision": 1}
    ]
    sim = session(client)
    path = f"/api/simulations/{sim['id']}/twin-run"
    assert client.get(path).json() is None
    body = {"run_id": str(uuid4()), "expected_version": 1, "twin": "flex"}
    response = client.post(path, json=body)
    assert response.status_code == 201, response.text
    result = response.json()
    assert (result["engine"], result["evidence"]) == ("teaching", "synthetic")
    assert result["status"] == "completed" and result["stop"] is None
    assert all(check["passed"] for check in result["checks"])
    assert len(result["frames"]) == 6
    last = result["frames"][-1]
    assert last["lid_parked"] and sum(last["mixture_components_ul"]) == 40
    assert [1500 - v for v in last["source_volumes_ul"]] == last["mixture_components_ul"]
    assert last["tips_used"] == [f"Tips__A{i}" for i in range(1, 5)]
    # A replay returns the stored receipt; the session itself stays native-pending.
    assert client.post(path, json=body).json() == result
    assert client.get(path).json() == result
    assert client.post(path, json=body | {"twin": f"device:{uuid4()}"}).status_code == 409
    assert client.get(f"/api/sessions/{sim['id']}").json()["evidence"] == "pending"
    assert client.get(f"/api/sessions/{sim['id']}/remote-run").json() is None
    assert run(client, sim, "flex", expected_version=2).status_code == 409
    assert run(client, sim, f"instrument:{uuid4()}").status_code == 404
    assert run(client, sim, "isaac").status_code == 422
    client.post("/api/auth/guest", json={"name": "Another learner"})
    assert client.get(path).status_code == 200 and client.get(path).json() is None
    assert client.post(path, json=body | {"run_id": str(uuid4())}).status_code == 404


def test_a_saved_device_twin_stops_at_what_it_has_not_declared(client):
    device = create_device(client)
    paired = client.post(f"/api/devices/{device['id']}/twin", json={"expected_version": 1}).json()
    key = f"device:{device['id']}"
    assert {"key": key, "kind": "device", "name": "Flex 01", "revision": 2} in client.get(
        "/api/simulations"
    ).json()["twins"]
    sim = session(client)
    stopped = run(client, sim, key).json()
    assert stopped["status"] == "stopped" and len(stopped["frames"]) == 1
    assert stopped["stop"] == {
        "step": 1,
        "layer": "state",
        "message": "Flex 01 has not declared that it can move labware",
    }
    assert not stopped["checks"][0]["passed"]
    payload = {
        "expected_version": paired["version"],
        "name": "Flex 01",
        "workcell": "Liquid handling",
        "connection": "native_api",
        "capabilities": ["pickup", "aspirate", "dispense", "drop", "move_labware"],
        "stage": 3,
    }
    assert client.put(f"/api/devices/{device['id']}", json=payload).status_code == 200
    completed = run(client, sim, key).json()
    assert completed["status"] == "completed" and completed["version"] == 2
    assert completed["twin"]["revision"] == 3


def test_a_saved_instrument_twin_applies_its_volume_and_tip_layers(client):
    twin_id, catalog = add(client, 0, template_id="liquid-handler")
    spec = TEMPLATES["liquid-handler"] | {
        "container": {"vessel": "plate", "max_volume_ul": 25},
    }
    confirm(client, twin_id, catalog["version"], spec)
    key = f"instrument:{twin_id}"
    assert key in [t["key"] for t in client.get("/api/simulations").json()["twins"]]
    sim = session(client)
    small = run(client, sim, key).json()
    assert (small["engine"], small["evidence"]) == ("simple_twin", "synthetic")
    assert small["stop"]["step"] == 4 and small["stop"]["layer"] == "volume"
    assert sum(small["frames"][-1]["mixture_components_ul"]) == 20
    other, catalog = add(
        client, client.get("/api/twins").json()["version"], template_id="liquid-handler"
    )
    tips = [{"name": "Pipette tips", "used_by": "mix", "per_use": 1, "stock": 2}]
    confirm(client, other, catalog["version"], TEMPLATES["liquid-handler"] | {"consumables": tips})
    short = run(client, sim, f"instrument:{other}").json()
    assert short["stop"]["step"] == 4 and short["stop"]["layer"] == "consumable"
    # A transfer robot holds no sample, so it is not offered.
    arm, catalog = add(
        client, client.get("/api/twins").json()["version"], template_id="transfer-arm"
    )
    confirm(client, arm, catalog["version"], TEMPLATES["transfer-arm"])
    assert f"instrument:{arm}" not in [
        t["key"] for t in client.get("/api/simulations").json()["twins"]
    ]


def test_a_gpu_owned_experiment_is_not_rerun_on_a_teaching_twin(store):
    service = MixingTwinService(store, SimpleTwinService(store, Settings()))
    sim = mixing_session(CreateMixing(session_id=uuid4())) | {"remote_active_run": str(uuid4())}
    store.put("alice", "session#" + sim["id"], sim, None)
    request = TwinRun(run_id=uuid4(), expected_version=1, twin="flex")
    with pytest.raises(HTTPException) as refused:
        service.run("alice", sim["id"], request)
    assert refused.value.status_code == 409
    assert service.get("alice", sim["id"]) is None
