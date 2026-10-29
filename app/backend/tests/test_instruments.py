import base64
import json
import xml.etree.ElementTree as ET
from uuid import uuid4

import pytest
from academy.simple_twins import TEMPLATES, usda
from fastapi import HTTPException

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\0" * 32).decode()
SPEC = {
    "name": "Shaker incubator",
    "parts": [{"size": [0.4, 0.3, 0.4], "position": [0, 0.15, 0], "color": "#336699"}],
    "operations": ["load", "mix", "heat", "wait"],
    "container": {"vessel": "plate", "max_volume_ul": 2000},
    "resource": {"slots": 2},
    "consumables": [],
    "limits": {"min_temp_c": 20, "max_temp_c": 60, "max_duration_s": 900},
    "assumptions": "Scale estimated from a door handle; interior not visible.",
}
BOX = {"size": [0.1, 0.1, 0.1], "position": [0, 0.05, 0], "color": "#000000"}


def completed(spec):
    return {
        "id": "resp_done",
        "status": "completed",
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": json.dumps(spec)}]}
        ],
    }


class FakeAstra:
    available = True

    def __init__(self, polls=(), begin_error=None):
        self.polls = list(polls)
        self.begin_error = begin_error
        self.submitted = 0

    def begin(self, data):
        self.submitted += 1
        if self.begin_error:
            raise self.begin_error
        return "resp_abc123", {"id": "resp_abc123", "status": "queued"}

    def poll(self, response_id):
        assert response_id == "resp_abc123"
        return self.polls.pop(0)


def add(client, version, **source):
    twin_id = str(uuid4())
    response = client.post(
        "/api/twins", json={"expected_version": version, "id": twin_id, **source}
    )
    assert response.status_code == 200, response.text
    return twin_id, response.json()


def confirm(client, twin_id, version, spec):
    response = client.put(
        f"/api/twins/{twin_id}/confirm", json={"expected_version": version, "spec": spec}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_unconfigured_astra_fails_closed_and_templates_still_work(client):
    catalog = client.get("/api/twins").json()
    assert catalog["astra_available"] is False
    assert catalog["real_available"] is False
    image = {"expected_version": 0, "id": str(uuid4()), "image": PNG}
    assert client.post("/api/twins", json=image).status_code == 503
    twin_id, catalog = add(client, 0, template_id="heater")
    assert catalog["twins"][0]["spec"] == TEMPLATES["heater"]
    assert catalog["twins"][0]["confirmed"] is False
    assert client.get(f"/api/twins/{twin_id}/usd").status_code == 409


def test_photo_generation_polls_validates_and_is_never_replayed(client, app):
    fake = FakeAstra(polls=[{"status": "in_progress"}, completed(SPEC)])
    app.state.twins.provider = fake
    twin_id, catalog = add(client, 0, image=PNG, mime="image/png")
    twin = catalog["twins"][0]
    assert (twin["status"], twin["source"], twin["spec"]) == ("generating", "astra_image", None)
    version = catalog["version"]
    poll = f"/api/twins/{twin_id}/poll"
    assert client.post(poll, json={"expected_version": version}).json()["version"] == version
    catalog = client.post(poll, json={"expected_version": version}).json()
    assert catalog["twins"][0]["status"] == "draft"
    assert catalog["twins"][0]["spec"]["name"] == "Shaker incubator"
    assert fake.submitted == 1


@pytest.mark.parametrize(
    "result",
    [
        completed(
            {**SPEC, "parts": [{"size": [9, 9, 9], "position": [0, 0, 0], "color": "#000000"}]}
        ),
        completed({**SPEC, "operations": ["load", "rm -rf"]}),
        completed({**SPEC, "parts": [BOX] * 5}),
        completed({**SPEC, "container": {"vessel": "none", "max_volume_ul": 0}}),
        {
            "status": "completed",
            "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}],
        },
        {"status": "failed"},
    ],
)
def test_out_of_bounds_or_refused_output_is_rejected(client, app, result):
    app.state.twins.provider = FakeAstra(polls=[result])
    twin_id, catalog = add(client, 0, image=PNG)
    catalog = client.post(
        f"/api/twins/{twin_id}/poll", json={"expected_version": catalog["version"]}
    ).json()
    assert catalog["twins"][0]["status"] == "failed"
    assert catalog["twins"][0]["spec"] is None


def test_unknown_submission_is_recorded_not_retried(client, app):
    fake = FakeAstra(begin_error=HTTPException(502, "Bedrock did not return a usable response."))
    app.state.twins.provider = fake
    _, catalog = add(client, 0, image=PNG)
    assert catalog["twins"][0]["status"] == "submission_unknown"
    assert fake.submitted == 1


def test_image_must_match_declared_type(client, app):
    app.state.twins.provider = FakeAstra()
    body = {"expected_version": 0, "id": str(uuid4()), "image": PNG, "mime": "image/jpeg"}
    assert client.post("/api/twins", json=body).status_code == 422


def build_cell(client):
    reader, catalog = add(client, 0, template_id="reader")
    heater, catalog = add(client, catalog["version"], template_id="heater")
    arm, catalog = add(client, catalog["version"], template_id="transfer-arm")
    for twin_id, key in [(reader, "reader"), (heater, "heater"), (arm, "transfer-arm")]:
        catalog = confirm(client, twin_id, catalog["version"], TEMPLATES[key])
    return reader, heater, arm, catalog


def test_multi_device_workflow_runs_on_mock_connectors(client):
    reader, heater, arm, catalog = build_cell(client)
    steps = [
        {"device_id": heater, "operation": "load"},
        {"device_id": heater, "operation": "heat", "value": 37},
        {"device_id": arm, "operation": "transfer", "source_id": heater, "target_id": reader},
        {"device_id": reader, "operation": "read"},
    ]
    saved = client.put(
        "/api/twins/workflow", json={"expected_version": catalog["version"], "steps": steps}
    )
    assert saved.status_code == 200, saved.text
    run = client.post("/api/twins/workflow/run", json={"expected_version": saved.json()["version"]})
    assert run.status_code == 200, run.text
    result = run.json()["runs"][0]
    assert (result["evidence"], result["connector"]) == ("synthetic", "mock_sila2")
    assert [t["location"] for t in result["trace"]] == [heater, heater, reader, reader]
    assert result["trace"][-1]["measurement"]["temperature_c"] == 37
    stale = client.post(
        "/api/twins/workflow/run", json={"expected_version": saved.json()["version"]}
    )
    assert stale.status_code == 409


def test_invalid_handoffs_and_capability_edits_are_rejected(client):
    reader, heater, arm, catalog = build_cell(client)
    version = catalog["version"]
    for steps in [
        [{"device_id": reader, "operation": "heat", "value": 37}],
        [{"device_id": heater, "operation": "load"}, {"device_id": reader, "operation": "read"}],
        [
            {"device_id": heater, "operation": "load"},
            {"device_id": arm, "operation": "transfer", "source_id": reader, "target_id": heater},
        ],
    ]:
        response = client.put(
            "/api/twins/workflow", json={"expected_version": version, "steps": steps}
        )
        assert response.status_code == 422, steps
    steps = [
        {"device_id": heater, "operation": "load"},
        {"device_id": heater, "operation": "heat", "value": 50},
    ]
    version = client.put(
        "/api/twins/workflow", json={"expected_version": version, "steps": steps}
    ).json()["version"]
    no_heat = {**TEMPLATES["heater"], "operations": ["load", "wait"]}
    response = client.put(
        f"/api/twins/{heater}/confirm", json={"expected_version": version, "spec": no_heat}
    )
    assert response.status_code == 422
    assert (
        client.request(
            "DELETE", f"/api/twins/{heater}", json={"expected_version": version}
        ).status_code
        == 409
    )
    assert (
        client.request(
            "DELETE", f"/api/twins/{reader}", json={"expected_version": version}
        ).status_code
        == 200
    )


def test_real_connector_fails_closed(client):
    twin_id, catalog = add(client, 0, template_id="reader")
    response = client.put(
        f"/api/twins/{twin_id}/connector",
        json={"expected_version": catalog["version"], "mode": "real"},
    )
    assert response.status_code == 409
    assert "qualified physical connector" in response.json()["detail"]


def test_exports_are_self_contained_usd_and_valid_sila_xml(client):
    twin_id, catalog = add(client, 0, template_id="heater")
    confirm(client, twin_id, catalog["version"], {**TEMPLATES["heater"], "name": "Heater <&> 2"})
    text = client.get(f"/api/twins/{twin_id}/usd").text
    assert text.startswith("#usda 1.0") and "@" not in text and "references" not in text
    package = client.get(f"/api/twins/{twin_id}/sila").json()
    feature = ET.fromstring(package["files"]["Heater2Mock.sila.xml"])
    ns = {"s": "http://www.sila-standard.org"}
    assert feature.find("s:Identifier", ns).text == "Heater2Mock"
    commands = [c.find("s:Identifier", ns).text for c in feature.findall("s:Command", ns)]
    assert commands == ["Load", "Heat", "Wait"]
    assert package["evidence"] == "synthetic"


def test_usda_is_deterministic():
    assert usda(TEMPLATES["reader"]) == usda(TEMPLATES["reader"])


def plan(client, version, steps):
    return client.put("/api/twins/workflow", json={"expected_version": version, "steps": steps})


@pytest.mark.parametrize(
    "layer, steps",
    [
        (
            "volume",
            lambda r, h, a: [
                {"device_id": h, "operation": "load", "value": 500},
                {"device_id": a, "operation": "transfer", "source_id": h, "target_id": r},
            ],
        ),
        (
            "constraint",
            lambda r, h, a: [
                {"device_id": h, "operation": "load", "value": 100},
                {"device_id": h, "operation": "heat", "value": 110},
            ],
        ),
        ("constraint", lambda r, h, a: [{"device_id": a, "operation": "wait", "value": 900}]),
        (
            "container",
            lambda r, h, a: [
                {"device_id": h, "operation": "load", "value": 100},
                {"device_id": a, "operation": "transfer", "source_id": h, "target_id": a},
            ],
        ),
    ],
)
def test_failures_are_attributed_to_a_twin_layer(client, layer, steps):
    reader, heater, arm, catalog = build_cell(client)
    response = plan(client, catalog["version"], steps(reader, heater, arm))
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["layer"] == layer


def test_consumables_run_out_and_value_edits_need_no_residual(client):
    handler, catalog = add(client, 0, template_id="liquid-handler")
    spec = TEMPLATES["liquid-handler"]
    one_tip = {**spec, "consumables": [{**spec["consumables"][0], "stock": 1}]}
    catalog = confirm(client, handler, catalog["version"], spec)
    catalog = confirm(client, handler, catalog["version"], one_tip)
    assert catalog["twins"][0]["revision"] == 2
    steps = [
        {"device_id": handler, "operation": "load", "value": 100},
        {"device_id": handler, "operation": "mix", "value": 5},
        {"device_id": handler, "operation": "mix", "value": 5},
    ]
    response = plan(client, catalog["version"], steps)
    assert response.json()["detail"]["layer"] == "consumable"
    run = plan(client, catalog["version"], steps[:2]).json()
    run = client.post("/api/twins/workflow/run", json={"expected_version": run["version"]}).json()
    assert run["runs"][0]["trace"][-1]["consumables"][handler] == {"Pipette tips": 0}


def test_added_detail_requires_an_open_residual_which_it_then_resolves(client):
    reader, catalog = add(client, 0, template_id="reader")
    spec = TEMPLATES["reader"]
    catalog = confirm(client, reader, catalog["version"], spec)
    detailed = {**spec, "parts": [*spec["parts"], BOX]}
    path = f"/api/twins/{reader}/confirm"
    refused = client.put(path, json={"expected_version": catalog["version"], "spec": detailed})
    assert refused.status_code == 422 and "geometry" in refused.json()["detail"]
    catalog = client.post(
        f"/api/twins/{reader}/residuals",
        json={
            "expected_version": catalog["version"],
            "layer": "geometry",
            "step": 2,
            "predicted": "Arm reaches the plate nest",
            "observed": "Lid hinge blocks the arm",
            "note": "Measured on the real reader.",
        },
    ).json()
    residual = catalog["twins"][0]["residuals"][0]
    assert (residual["revision"], residual["resolved_in"], residual["evidence"]) == (
        1,
        None,
        "learner_observation",
    )
    catalog = confirm(client, reader, catalog["version"], detailed)
    twin = catalog["twins"][0]
    assert twin["revision"] == 2 and twin["residuals"][0]["resolved_in"] == 2
    assert len(twin["spec"]["parts"]) == 3


def test_no_two_routes_share_a_method_and_path(app):
    # FastAPI silently lets the first registration win; a shared path breaks one feature.
    seen = [(m, r.path) for r in app.routes for m in getattr(r, "methods", ()) or ()]
    assert len(seen) == len(set(seen)), sorted({x for x in seen if seen.count(x) > 1})
