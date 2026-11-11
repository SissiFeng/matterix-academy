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

    # Every role was given an instrument to review; none is confirmed for the learner.
    chosen = {t["id"]: t for t in catalog["twins"]}
    assert set(brief["bindings"]) == {"heater", "robot", "reader"}
    assert all(not chosen[twin_id]["confirmed"] for twin_id in brief["bindings"].values())
    apply = lambda v: client.put("/api/twins/workflow/brief/apply", json={"expected_version": v})  # noqa: E731
    response = apply(catalog["version"])
    assert response.status_code == 422
    assert "Confirm the instrument for Heating station" in response.json()["detail"]["message"]

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


def drafted(client, app, draft=DRAFT):
    app.state.twins.provider = FakeBriefs(polls=[done(draft)])
    catalog = describe(client, 0).json()
    response = client.post(
        "/api/twins/workflow/brief/poll", json={"expected_version": catalog["version"]}
    )
    assert response.status_code == 200, response.text
    return response.json()


def chosen(catalog, role):
    twin_id = catalog["brief"]["bindings"][role]
    return next(t for t in catalog["twins"] if t["id"] == twin_id)


def test_instruments_are_chosen_from_the_description_and_accepted_in_one_step(client, app):
    catalog = drafted(client, app)
    # The plate reader and the arm come from the library; the vessel follows the role.
    assert chosen(catalog, "reader")["source"].endswith("_asset")
    assert chosen(catalog, "reader")["spec"]["container"]["vessel"] == "plate"
    assert "transfer" in chosen(catalog, "robot")["spec"]["operations"]
    assert chosen(catalog, "heater")["spec"]["container"]["vessel"] == "plate"
    accept = client.put(
        "/api/twins/workflow/brief/accept", json={"expected_version": catalog["version"]}
    )
    assert accept.status_code == 200, accept.text
    catalog = accept.json()
    assert all(chosen(catalog, role)["confirmed"] for role in ("heater", "robot", "reader"))
    assert [s["operation"] for s in catalog["steps"]] == ["load", "heat", "transfer", "read"]
    assert catalog["steps"][2]["device_id"] == catalog["brief"]["bindings"]["robot"]
    stale = client.put(
        "/api/twins/workflow/brief/accept", json={"expected_version": catalog["version"] - 1}
    )
    assert stale.status_code == 409


def test_a_named_instrument_is_the_one_chosen(client, app):
    named = json.loads(json.dumps(DRAFT))
    named["roles"][2].update(model="CLARIOstar Plus", query="reader")
    named["roles"][1].update(model="UR5e")
    catalog = drafted(client, app, named)
    assert chosen(catalog, "reader")["asset"]["id"] == "bmg_clariostarplus"
    assert chosen(catalog, "robot")["asset"]["id"] == "ur5e-2f140"


def test_an_instrument_the_workcell_has_is_used_before_adding_one(client, app):
    reader, catalog = add(client, 0, template_id="reader")
    catalog = confirm(client, reader, catalog["version"], TEMPLATES["reader"])
    app.state.twins.provider = FakeBriefs(polls=[done(DRAFT)])
    catalog = describe(client, catalog["version"]).json()
    catalog = client.post(
        "/api/twins/workflow/brief/poll", json={"expected_version": catalog["version"]}
    ).json()
    assert catalog["brief"]["bindings"]["reader"] == reader
    assert len(catalog["twins"]) == 3  # the reader, plus a heater and an arm


def test_cleared_roles_can_be_chosen_again_without_touching_the_rest(client, app):
    catalog = drafted(client, app)
    kept = catalog["brief"]["bindings"]["heater"]
    cleared = client.put(
        "/api/twins/workflow/brief/bind",
        json={"expected_version": catalog["version"], "role": "reader", "twin_id": None},
    ).json()
    assert "reader" not in cleared["brief"]["bindings"]
    again = client.put(
        "/api/twins/workflow/brief/choose", json={"expected_version": cleared["version"]}
    )
    assert again.status_code == 200, again.text
    catalog = again.json()
    # The reader twin added the first time is free again, so it is reused, not duplicated.
    assert catalog["brief"]["bindings"]["heater"] == kept
    assert "reader" in catalog["brief"]["bindings"] and len(catalog["twins"]) == 3
    none = client.put("/api/twins/workflow/brief/choose", json={"expected_version": 0})
    assert none.status_code == 409


class FakeConverse:
    """Bedrock Converse returning the given tool inputs in order; an exception is raised."""

    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.calls = []

    def converse(self, **request):
        self.calls.append(json.loads(json.dumps(request)))
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "toolUse": {
                                "toolUseId": f"t{len(self.calls)}",
                                "name": "x",
                                "input": output,
                            }
                        }
                    ],
                }
            }
        }


def nova(app, *outputs):
    from academy.nova_briefs import NovaBriefs
    from academy.settings import Settings

    fake = FakeConverse(*outputs)
    settings = Settings(brief_model="us.amazon.nova-pro-v1:0", brief_region="us-east-1")
    app.state.twins.drafter = NovaBriefs(settings, client=fake)
    return fake


def poll(client, version):
    return client.post("/api/twins/workflow/brief/poll", json={"expected_version": version})


def test_nova_drafts_through_the_lambda_role_and_corrects_a_rejected_draft(client, app):
    station_with_transfer = json.loads(json.dumps(DRAFT))
    station_with_transfer["roles"][0]["operations"].append("transfer")
    fake = nova(app, station_with_transfer, DRAFT)
    catalog = client.get("/api/twins").json()
    assert catalog["brief_available"] and catalog["brief_model"] == "Amazon Nova Pro"
    # Astra stays off: photo sketches still need it.
    assert catalog["astra_available"] is False

    first = describe(client, catalog["version"])
    assert first.status_code == 200, first.text
    brief = first.json()["brief"]
    assert brief["status"] == "generating" and "exchange" not in brief
    assert fake.calls[0]["modelId"] == "us.amazon.nova-pro-v1:0"
    assert fake.calls[0]["toolConfig"]["toolChoice"] == {
        "tool": {"name": "teaching_workflow_draft"}
    }

    done_ = poll(client, first.json()["version"])
    assert done_.status_code == 200, done_.text
    assert done_.json()["brief"]["status"] == "draft"
    assert done_.json()["brief"]["draft"]["roles"][0]["operations"] == ["load", "heat"]
    # As with Astra, every role the steps use is given an instrument to review.
    assert set(done_.json()["brief"]["bindings"]) == {"heater", "robot", "reader"}
    # The second call carried the first draft and why it was rejected.
    feedback = fake.calls[1]["messages"][-1]["content"][0]["toolResult"]
    assert (
        feedback["status"] == "error" and "must not list transfer" in feedback["content"][0]["text"]
    )
    assert "exchange" not in app.state.twins.get("guest-unused") and not fake.outputs


def test_nova_gives_up_after_its_attempts(client, app):
    from academy.nova_briefs import ATTEMPTS

    bad = {**DRAFT, "steps": []}
    fake = nova(app, *[bad] * ATTEMPTS)
    catalog = describe(client, client.get("/api/twins").json()["version"]).json()
    for _ in range(ATTEMPTS - 1):
        catalog = poll(client, catalog["version"]).json()
    assert len(fake.calls) == ATTEMPTS
    assert catalog["brief"]["status"] == "failed"
    assert "did not match the workflow schema" in catalog["brief"]["message"]
    # Finished drafts are never asked for again.
    assert poll(client, catalog["version"]).json()["brief"]["status"] == "failed"
    assert len(fake.calls) == ATTEMPTS


def test_overlapping_polls_never_repeat_a_claimed_nova_call(app):
    import time

    service = app.state.twins
    fake = nova(app, DRAFT)
    brief = {
        "id": "b1",
        "status": "generating",
        "source": "nova",
        "draft": None,
        "bindings": {},
        "message": "",
        "exchange": service.drafter.begin("Heat a plate, then read it."),
        "busy_until": time.time() + 10,
    }
    service.save("nova-owner", {**service.get("nova-owner"), "brief": brief}, 0)
    assert service._nova_attempt("nova-owner", "b1")["brief"]["status"] == "generating"
    assert fake.calls == []
    record = service.get("nova-owner")
    record["brief"]["busy_until"] = 0
    service.save("nova-owner", record, record["version"])
    assert service._nova_attempt("nova-owner", "b1")["brief"]["status"] == "draft"
    assert len(fake.calls) == 1 and "exchange" not in service.get("nova-owner")["brief"]


def test_a_failed_nova_call_says_so_and_the_settings_pair_is_checked(client, app):
    import pytest
    from academy.settings import Settings
    from botocore.exceptions import ClientError

    nova(
        app, ClientError({"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "Converse")
    )
    catalog = describe(client, client.get("/api/twins").json()["version"]).json()
    assert catalog["brief"]["status"] == "failed"
    assert catalog["brief"]["message"].startswith("Amazon Nova Pro did not return a draft")
    with pytest.raises(ValueError, match="Nova inference profile"):
        Settings(brief_model="openai.gpt-6-astra", brief_region="us-east-1")
    with pytest.raises(ValueError, match="together"):
        Settings(brief_model="us.amazon.nova-pro-v1:0")


def test_a_draft_that_loads_a_sample_twice_is_sent_back():
    import pytest
    from pydantic import ValidationError

    twice = json.loads(json.dumps(DRAFT))
    twice["steps"].insert(
        3, {"role": "reader", "operation": "load", "source_role": "", "target_role": "", "value": 1}
    )
    with pytest.raises(ValidationError, match="Step 4 loads sample again after step 1"):
        Draft.model_validate(twice)
    # A second sample may be loaded on its own.
    twice["steps"][3]["sample"] = "plate-b"
    Draft.model_validate(twice)


def test_a_draft_acting_where_the_sample_is_not_is_sent_back():
    import pytest
    from pydantic import ValidationError

    def with_steps(*steps):
        draft = json.loads(json.dumps(DRAFT))
        draft["steps"] = [
            {"source_role": "", "target_role": "", "value": 1, **step} for step in steps
        ]
        return draft

    load = {"role": "heater", "operation": "load", "value": 150}
    move = {
        "role": "robot",
        "operation": "transfer",
        "source_role": "heater",
        "target_role": "reader",
    }
    with pytest.raises(ValidationError, match="before any step loads it"):
        Draft.model_validate(with_steps({"role": "heater", "operation": "heat", "value": 37}))
    with pytest.raises(ValidationError, match="sample is at reader, not heater"):
        Draft.model_validate(
            with_steps(load, move, {"role": "heater", "operation": "heat", "value": 37})
        )
    with pytest.raises(ValidationError, match="but it is at reader"):
        Draft.model_validate(with_steps(load, move, move))
    robot_holding = with_steps(load, move)
    robot_holding["roles"][1]["operations"] = ["load", "transfer"]
    with pytest.raises(ValidationError, match="moves samples, so it must not hold one"):
        Draft.model_validate(robot_holding)
    Draft.model_validate(with_steps(load, move, {"role": "reader", "operation": "read"}))
