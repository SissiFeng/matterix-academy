import base64
import json
import xml.etree.ElementTree as ET
from uuid import uuid4

import pytest
from academy.chemlab import CHEMLAB
from academy.simple_twins import TEMPLATES, TwinSpec, usda
from academy.simready import SIMREADY
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


UNKNOWN = {
    "library_id": "none",
    "alternatives": [],
    "maker": "",
    "model": "",
    "confidence": "low",
    "evidence": "No legible label.",
}
XPR = {
    "library_id": "chemlab:mt_xpr204e",
    "alternatives": ["chemlab:ohaus_px224e"],
    "maker": "METTLER TOLEDO",
    "model": "XPR204E",
    "confidence": "high",
    "evidence": "XPR204E badge on the terminal.",
}


def completed(spec, identification=UNKNOWN):
    text = json.dumps({"identification": identification, "twin": spec})
    return {
        "id": "resp_done",
        "status": "completed",
        "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
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
    assert catalog["twins"][0]["matches"] == []  # no library pick and no legible model
    assert fake.submitted == 1


def photo_twin(client, app, result):
    app.state.twins.provider = FakeAstra(polls=[result])
    twin_id, catalog = add(client, 0, image=PNG)
    catalog = client.post(
        f"/api/twins/{twin_id}/poll", json={"expected_version": catalog["version"]}
    ).json()
    return twin_id, catalog


def match(client, twin_id, version, collection, asset_id):
    return client.put(
        f"/api/twins/{twin_id}/match",
        json={"expected_version": version, "collection": collection, "asset_id": asset_id},
    )


def test_photo_identification_offers_verified_library_matches_to_replace_the_sketch(client, app):
    twin_id, catalog = photo_twin(client, app, completed(SPEC, XPR))
    twin = catalog["twins"][0]
    assert (twin["status"], twin["source"], twin["spec"]["name"]) == (
        "draft",
        "astra_image",
        "Shaker incubator",
    )
    assert twin["identification"] == XPR
    assert [(m["id"], m["suggested_by"], m["verified"]) for m in twin["matches"]] == [
        ("mt_xpr204e", "astra", True),
        ("ohaus_px224e", "astra", False),
    ]
    response = match(client, twin_id, catalog["version"], "chemlab", "mt_xpr204e")
    assert response.status_code == 200, response.text
    twin = response.json()["twins"][0]
    assert (twin["source"], twin["spec"]) == ("chemlab_asset", CHEMLAB["mt_xpr204e"]["spec"])
    assert twin["asset"]["attribution"] == CHEMLAB["mt_xpr204e"]["attribution"]
    assert twin["image_sha256"] and twin["confirmed"] is False
    catalog = confirm(client, twin_id, response.json()["version"], twin["spec"])
    assert match(client, twin_id, catalog["version"], "chemlab", "ohaus_px224e").status_code == 409


def test_model_read_off_the_label_finds_entries_astra_did_not_pick(client, app):
    read = {**UNKNOWN, "model": "5910 Ri", "confidence": "medium"}
    _, catalog = photo_twin(client, app, completed(SPEC, read))
    matches = catalog["twins"][0]["matches"]
    assert [(m["id"], m["suggested_by"], m["verified"]) for m in matches] == [
        ("eppendorf_5910ri", "label_text", True)
    ]


def test_only_offered_matches_can_replace_a_sketch(client, app):
    twin_id, catalog = photo_twin(client, app, completed(SPEC, XPR))
    for collection, asset_id in [("chemlab", "eppendorf_5910ri"), ("simready", "franka-fr3")]:
        response = match(client, twin_id, catalog["version"], collection, asset_id)
        assert response.status_code == 422
    assert client.get("/api/twins").json()["twins"][0]["source"] == "astra_image"


def test_a_failed_sketch_with_a_valid_identification_recovers_through_a_match(client, app):
    twin_id, catalog = photo_twin(client, app, completed({**SPEC, "parts": [BOX] * 5}, XPR))
    twin = catalog["twins"][0]
    assert (twin["status"], twin["spec"]) == ("failed", None)
    assert "library match" in twin["message"] and twin["matches"]
    response = match(client, twin_id, catalog["version"], "chemlab", "mt_xpr204e")
    assert response.status_code == 200 and response.json()["twins"][0]["status"] == "draft"


def test_identification_outside_the_library_is_rejected_not_matched(client, app):
    bogus = {**XPR, "library_id": "chemlab:not_listed", "alternatives": [], "model": ""}
    _, catalog = photo_twin(client, app, completed(SPEC, bogus))
    assert catalog["twins"][0]["matches"] == []


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
    assert (result["evidence"], result["connector"]) == ("synthetic", "in_process_mock")
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


def test_simready_assets_are_pinned_attributed_one_box_specs():
    for asset in SIMREADY.values():
        assert TwinSpec.model_validate(asset["spec"]).model_dump(mode="json") == asset["spec"]
        assert len(asset["spec"]["parts"]) == 1
        assert asset["license"] == "CC-BY-4.0"
        assert len(asset["revision"]) == 40 and asset["revision"] in asset["url"]


def test_simready_asset_starts_an_attributed_twin_without_external_references(client):
    twin_id, catalog = add(client, 0, simready_id="forgecad-microplate-reader")
    twin = catalog["twins"][0]
    asset = SIMREADY["forgecad-microplate-reader"]
    assert catalog["simready"]["forgecad-microplate-reader"] == asset
    assert (twin["source"], twin["spec"], twin["confirmed"]) == (
        "simready_asset",
        asset["spec"],
        False,
    )
    assert twin["asset"]["url"] == asset["url"] and "spec" not in twin["asset"]
    confirm(client, twin_id, catalog["version"], twin["spec"])
    text = client.get(f"/api/twins/{twin_id}/usd").text
    assert asset["attribution"] in text and asset["url"] in text
    assert "@" not in text and "references" not in text and "payload" not in text
    readme = client.get(f"/api/twins/{twin_id}/sila").json()["files"]["README.md"]
    assert asset["attribution"] in readme


@pytest.mark.parametrize(
    "source",
    [
        {"simready_id": "not-in-catalog"},
        {"simready_id": "franka-fr3", "template_id": "heater"},
        {"simready_id": "franka-fr3", "image": PNG},
        {"chemlab_id": "not-in-catalog"},
        {"chemlab_id": "mt_xpr204e", "simready_id": "franka-fr3"},
        {"chemlab_id": "mt_xpr204e", "template_id": "heater"},
    ],
)
def test_simready_source_must_be_a_single_known_asset(client, source):
    response = client.post("/api/twins", json={"expected_version": 0, "id": str(uuid4()), **source})
    assert response.status_code == 422
    assert client.get("/api/twins").json()["twins"] == []


def test_simready_twins_run_a_workflow_on_mock_connectors(client):
    ids = {}
    catalog = {"version": 0}
    for key in ["forgecad-laboratory-incubator", "forgecad-microplate-reader", "franka-fr3"]:
        ids[key], catalog = add(client, catalog["version"], simready_id=key)
        catalog = confirm(client, ids[key], catalog["version"], SIMREADY[key]["spec"])
    incubator, reader, arm = ids.values()
    steps = [
        {"device_id": incubator, "operation": "load", "value": 200},
        {"device_id": incubator, "operation": "heat", "value": 37},
        {"device_id": arm, "operation": "transfer", "source_id": incubator, "target_id": reader},
        {"device_id": reader, "operation": "read"},
    ]
    version = plan(client, catalog["version"], steps).json()["version"]
    run = client.post("/api/twins/workflow/run", json={"expected_version": version})
    assert run.status_code == 200, run.text
    assert run.json()["runs"][0]["trace"][-1]["measurement"]["temperature_c"] == 37


def test_chemlab_assets_are_pinned_non_commercial_one_box_specs():
    for asset in CHEMLAB.values():
        assert TwinSpec.model_validate(asset["spec"]).model_dump(mode="json") == asset["spec"]
        assert len(asset["spec"]["parts"]) == 1
        assert asset["license"] == "CC-BY-NC-4.0" and "CC-BY-NC-4.0" in asset["attribution"]
        assert "non-commercial" in asset["spec"]["assumptions"]
        assert len(asset["revision"]) == 40 and asset["revision"] in asset["url"]
    assert len(CHEMLAB) == 203 and sum(a["featured"] for a in CHEMLAB.values()) == 9
    balance = CHEMLAB["mt_xpr204e"]["spec"]["parts"][0]
    assert balance["size"] == [0.209, 0.339, 0.4604]  # Z-up catalog size, Y-up twin
    assert CHEMLAB["agilent_hplc1260"]["spec"]["operations"] == ["load", "read", "wait"]
    assert CHEMLAB["ika_rv10_digital_v"]["spec"]["operations"] == ["load", "heat", "wait"]


def test_library_search_ranks_name_matches_and_spans_both_collections(client):
    def search(q):
        response = client.get("/api/twins/library", params={"q": q})
        assert response.status_code == 200, response.text
        return response.json()

    featured = search("")
    assert featured["size"] == len(CHEMLAB) + len(SIMREADY)
    assert {r["collection"] for r in featured["results"]} == {"chemlab", "simready"}
    assert all(
        CHEMLAB[r["id"]]["featured"] for r in featured["results"] if r["collection"] == "chemlab"
    )
    assert [r["id"] for r in search("XPR204E")["results"]] == ["mt_xpr204e"]
    readers = search("plate reader")["results"]
    assert {(r["collection"], r["id"]) for r in readers} >= {
        ("simready", "forgecad-microplate-reader"),
        ("chemlab", "bmg_clariostarplus"),
    }
    assert search("no such instrument")["total"] == 0
    hit = search("XPR204E")["results"][0]
    assert hit["license"] == "CC-BY-NC-4.0" and hit["size_m"] == [0.209, 0.4604, 0.339]
    assert client.get("/api/twins/library", params={"q": "x" * 81}).status_code == 422


def test_chemlab_asset_starts_an_attributed_twin_without_external_references(client):
    twin_id, catalog = add(client, 0, chemlab_id="mt_xpr204e")
    twin = catalog["twins"][0]
    asset = CHEMLAB["mt_xpr204e"]
    assert "chemlab" not in catalog  # searched, never shipped with every catalog
    assert (twin["source"], twin["spec"], twin["confirmed"]) == (
        "chemlab_asset",
        asset["spec"],
        False,
    )
    assert twin["asset"]["url"] == asset["url"] and "spec" not in twin["asset"]
    confirm(client, twin_id, catalog["version"], twin["spec"])
    text = client.get(f"/api/twins/{twin_id}/usd").text
    assert asset["attribution"] in text and asset["url"] in text
    assert "@" not in text and "references" not in text and "payload" not in text
    readme = client.get(f"/api/twins/{twin_id}/sila").json()["files"]["README.md"]
    assert asset["attribution"] in readme


def test_chemlab_twins_run_a_workflow_on_mock_connectors(client):
    ids = {}
    catalog = {"version": 0}
    for key in ["ika_ks4000", "bmg_clariostarplus", "brooks_preciseflex_400"]:
        ids[key], catalog = add(client, catalog["version"], chemlab_id=key)
        catalog = confirm(client, ids[key], catalog["version"], CHEMLAB[key]["spec"])
    shaker, reader, arm = ids.values()
    steps = [
        {"device_id": shaker, "operation": "load", "value": 200},
        {"device_id": shaker, "operation": "heat", "value": 60},
        {"device_id": arm, "operation": "transfer", "source_id": shaker, "target_id": reader},
        {"device_id": reader, "operation": "read"},
    ]
    planned = plan(client, catalog["version"], steps)
    assert planned.status_code == 200, planned.text
    run = client.post(
        "/api/twins/workflow/run", json={"expected_version": planned.json()["version"]}
    )
    assert run.status_code == 200, run.text
    assert run.json()["runs"][0]["trace"][-1]["measurement"]["temperature_c"] == 60


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


def test_owner_isolation_includes_assets_and_runnable_bundle(client, app):
    import io
    import zipfile

    from fastapi.testclient import TestClient

    twin_id, catalog = add(client, 0, template_id="heater")
    confirm(client, twin_id, catalog["version"], TEMPLATES["heater"])
    with TestClient(app) as other:
        assert other.get(f"/api/twins/{twin_id}/sila.zip").status_code == 401
        other.post("/api/auth/guest", json={"name": "Grace"})
        assert other.get("/api/twins").json()["twins"] == []
        for suffix in ("usd", "sila", "sila.zip"):
            assert other.get(f"/api/twins/{twin_id}/{suffix}").status_code == 404
    result = client.get(f"/api/twins/{twin_id}/sila.zip")
    assert result.status_code == 200
    with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
        assert "mock_sila.py" in archive.namelist()
        assert "mock_contract.py" in archive.namelist()
        manifest = json.loads(archive.read("workspace.json"))
        assert manifest["twins"][0]["id"] == twin_id


def test_bedrock_request_has_a_complete_strict_output_schema(monkeypatch):
    import httpx
    from academy.settings import Settings
    from academy.simple_twins import BedrockTwins, CreateTwin

    calls = []

    def request(method, url, **kwargs):
        assert (
            method == "POST"
            and url == "https://bedrock-mantle.us-west-2.api.aws/openai/v1/responses"
        )
        assert kwargs["headers"]["Authorization"] == "Bearer test-only"
        payload = kwargs["json"]
        assert payload["model"] == "openai.gpt-6-astra"
        assert payload["input"][0]["content"][1]["image_url"].startswith("data:image/png;base64,")

        def strict(schema):
            if schema.get("type") == "object":
                assert schema["additionalProperties"] is False
                assert set(schema["required"]) == set(schema["properties"])
                for child in schema["properties"].values():
                    strict(child)
            if schema.get("type") == "array":
                strict(schema["items"])

        schema = payload["text"]["format"]["schema"]
        strict(schema)
        keys = schema["properties"]["identification"]["properties"]["library_id"]["enum"]
        assert "chemlab:mt_xpr204e" in keys and "simready:franka-fr3" in keys
        assert keys[-1] == "none" and len(keys) == len(CHEMLAB) + len(SIMREADY) + 1
        prompt = payload["input"][0]["content"][0]["text"]
        assert "chemlab:mt_xpr204e | METTLER TOLEDO XPR204E analytical balance" in prompt
        calls.append(payload)
        return httpx.Response(
            200,
            request=httpx.Request(method, url),
            json={"id": "resp_schema_test", "status": "queued"},
        )

    monkeypatch.setattr(httpx, "request", request)
    provider = BedrockTwins(Settings(twin_region="us-west-2", twin_api_key="test-only"))
    response_id, _ = provider.begin(CreateTwin(expected_version=0, id=uuid4(), image=PNG))
    assert response_id == "resp_schema_test" and len(calls) == 1


def test_saved_run_pins_specs_even_after_twin_revision(client):
    twin_id, catalog = add(client, 0, template_id="heater")
    catalog = confirm(client, twin_id, catalog["version"], TEMPLATES["heater"])
    catalog = plan(
        client, catalog["version"], [{"device_id": twin_id, "operation": "load", "value": 100}]
    ).json()
    catalog = client.post(
        "/api/twins/workflow/run", json={"expected_version": catalog["version"]}
    ).json()
    pinned = catalog["runs"][0]["twins"][0]
    revised = {**TEMPLATES["heater"], "name": "Revised heater"}
    catalog = confirm(client, twin_id, catalog["version"], revised)
    assert catalog["twins"][0]["spec"]["name"] == "Revised heater"
    assert catalog["runs"][0]["twins"][0] == pinned
    assert pinned["spec"]["name"] == "Heating station" and pinned["revision"] == 1


def test_no_two_routes_share_a_method_and_path(app):
    # FastAPI silently lets the first registration win; a shared path breaks one feature.
    seen = [(m, r.path) for r in app.routes for m in getattr(r, "methods", ()) or ()]
    assert len(seen) == len(set(seen)), sorted({x for x in seen if seen.count(x) > 1})
