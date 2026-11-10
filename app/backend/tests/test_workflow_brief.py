import json

from academy.simple_twins import TEMPLATES
from academy.workflow_brief import Draft, schema
from test_instruments import FakeAstra, add, confirm

DRAFT = {
    "roles": [
        {
            "key": "heater",
            "name": "Heating station",
            "operations": ["load", "heat"],
            "vessel": "plate",
            "query": "plate heater",
        },
        {
            "key": "robot",
            "name": "Transfer robot",
            "operations": ["transfer"],
            "vessel": "none",
            "query": "robot arm",
        },
        {
            "key": "reader",
            "name": "Plate reader",
            "operations": ["load", "read"],
            "vessel": "plate",
            "query": "plate reader",
        },
    ],
    "steps": [
        {"role": "heater", "operation": "load", "source_role": "", "target_role": "", "value": 150},
        {"role": "heater", "operation": "heat", "source_role": "", "target_role": "", "value": 37},
        {
            "role": "robot",
            "operation": "transfer",
            "source_role": "heater",
            "target_role": "reader",
            "value": 1,
        },
        {"role": "reader", "operation": "read", "source_role": "", "target_role": "", "value": 1},
    ],
    "assumptions": ["Four plates reduced to one tracked sample."],
}


class FakeBriefs(FakeAstra):
    def __init__(self, polls=()):
        super().__init__(polls)
        self.texts = []

    def begin_brief(self, text):
        self.texts.append(text)
        return "resp_abc123", {"id": "resp_abc123", "status": "queued"}


def done(output):
    text = json.dumps(output)
    return {
        "id": "resp_abc123",
        "status": "completed",
        "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
    }


def describe(client, version, text="Heat a plate to 37 °C, then read it on the plate reader."):
    return client.post(
        "/api/twins/workflow/brief", json={"expected_version": version, "text": text}
    )


def test_schema_is_strict_and_the_draft_model_agrees():
    def strict(node):
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])
            for child in node["properties"].values():
                strict(child)
        if node.get("type") == "array":
            strict(node["items"])

    strict(schema())
    assert Draft.model_validate(DRAFT)


def test_unconfigured_astra_fails_closed(client):
    response = describe(client, 0)
    assert response.status_code == 503
    assert client.get("/api/twins").json()["brief"] is None


def test_description_becomes_roles_then_a_saved_workflow(client, app):
    fake = FakeBriefs(polls=[{"status": "in_progress"}, done(DRAFT)])
    app.state.twins.provider = fake
    response = describe(client, 0)
    assert response.status_code == 200, response.text
    catalog = response.json()
    assert catalog["brief"]["status"] == "generating" and fake.texts
    version = catalog["version"]
    # A second description is not submitted while a draft is in flight.
    assert describe(client, version).status_code == 409
    poll = lambda v: client.post("/api/twins/workflow/brief/poll", json={"expected_version": v})  # noqa: E731
    first = poll(version)
    assert first.status_code == 200, first.text
    assert first.json()["version"] == version  # still in progress, nothing saved
    catalog = poll(version).json()
    brief = catalog["brief"]
    assert brief["status"] == "draft" and [r["key"] for r in brief["draft"]["roles"]] == [
        "heater",
        "robot",
        "reader",
    ]

    apply = lambda v: client.put("/api/twins/workflow/brief/apply", json={"expected_version": v})  # noqa: E731
    catalog = client.get("/api/twins").json()
    response = apply(catalog["version"])
    assert response.status_code == 422
    assert "Choose an instrument for Heating station" in response.json()["detail"]["message"]

    ids = {}
    for role, template in [("heater", "heater"), ("robot", "transfer-arm"), ("reader", "reader")]:
        ids[role], catalog = add(client, catalog["version"], template_id=template)
        bound = client.put(
            "/api/twins/workflow/brief/bind",
            json={"expected_version": catalog["version"], "role": role, "twin_id": ids[role]},
        )
        assert bound.status_code == 200, bound.text
        catalog = bound.json()
    assert catalog["brief"]["bindings"] == ids
    response = apply(catalog["version"])
    assert "Confirm the instrument for Heating station" in response.json()["detail"]["message"]
    for role, template in [("heater", "heater"), ("robot", "transfer-arm"), ("reader", "reader")]:
        catalog = confirm(client, ids[role], catalog["version"], TEMPLATES[template])
    response = apply(catalog["version"])
    assert response.status_code == 200, response.text
    steps = response.json()["steps"]
    assert [s["device_id"] for s in steps] == [
        ids["heater"],
        ids["heater"],
        ids["robot"],
        ids["reader"],
    ]
    assert (steps[2]["source_id"], steps[2]["target_id"]) == (ids["heater"], ids["reader"])
    assert steps[0]["value"] == 150

    # Removing a bound instrument from the workflow and the workcell unbinds it.
    catalog = response.json()
    catalog = client.put(
        "/api/twins/workflow", json={"expected_version": catalog["version"], "steps": []}
    ).json()
    catalog = client.request(
        "DELETE", f"/api/twins/{ids['reader']}", json={"expected_version": catalog["version"]}
    ).json()
    assert "reader" not in catalog["brief"]["bindings"]


def test_invalid_or_refused_drafts_are_never_applied(client, app):
    broken = {**DRAFT, "steps": [{**DRAFT["steps"][2], "target_role": "heater"}]}
    refusal = {
        "id": "resp_abc123",
        "status": "completed",
        "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}],
    }
    for result, message in [(done(broken), "workflow schema"), (refusal, "declined")]:
        app.state.twins.provider = FakeBriefs(polls=[result])
        catalog = client.get("/api/twins").json()
        catalog = describe(client, catalog["version"]).json()
        catalog = client.post(
            "/api/twins/workflow/brief/poll", json={"expected_version": catalog["version"]}
        ).json()
        assert catalog["brief"]["status"] == "failed"
        assert message in catalog["brief"]["message"] and catalog["brief"]["draft"] is None
    response = client.put(
        "/api/twins/workflow/brief/bind",
        json={"expected_version": catalog["version"], "role": "heater", "twin_id": None},
    )
    assert response.status_code == 409


def test_bedrock_brief_request_uses_strict_json_schema(monkeypatch):
    from academy.settings import Settings
    from academy.simple_twins import BedrockTwins

    sent = {}

    def fake_request(self, method, path, **kwargs):
        sent.update(method=method, path=path, **kwargs)
        return {"id": "resp_xyz", "status": "queued"}

    monkeypatch.setattr(BedrockTwins, "request", fake_request)
    provider = BedrockTwins(Settings(twin_region="us-west-2", twin_api_key="test-only"))
    response_id, _ = provider.begin_brief("Heat then read a plate.")
    assert response_id == "resp_xyz"
    fmt = sent["json"]["text"]["format"]
    assert fmt["strict"] is True and fmt["schema"] == schema()
    assert sent["json"]["input"][0]["content"][0]["text"].endswith("Heat then read a plate.")
