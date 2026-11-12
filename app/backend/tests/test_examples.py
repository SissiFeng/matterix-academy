"""Example workcells open in the planner with a layout the arm can run."""

import pytest
from academy.examples import EXAMPLES
from test_instruments import add


def test_examples_are_listed_with_their_instruments(client):
    listed = client.get("/api/twins/examples").json()["examples"]
    assert [e["id"] for e in listed] == list(EXAMPLES)
    assert len(listed) == 7
    first = listed[0]
    assert first["instruments"] == [
        "Liquid handler (Opentrons Flex)",
        "Plate reader (CLARIOstar Plus)",
        "UR5e arm",
    ]
    # One example is kept to show an instrument the arm cannot serve.
    assert [e["id"] for e in listed if not e["placed"]] == ["flex-shaker-reader"]


@pytest.mark.parametrize("key", list(EXAMPLES))
def test_an_example_opens_ready_to_run(client, key):
    opened = client.put(f"/api/twins/examples/{key}", json={"expected_version": 0})
    assert opened.status_code == 200, opened.text
    catalog = opened.json()
    case = EXAMPLES[key]
    assert len(catalog["twins"]) == len(case["instruments"]) + 1
    assert all(t["confirmed"] for t in catalog["twins"])
    assert len(catalog["steps"]) == len(case["steps"])
    if case["placements"] is None:
        assert catalog["layout"] is None
        return
    # The saved layout carries every transfer of the workflow.
    checked = client.post("/api/twins/layout/preview", json=catalog["layout"]).json()
    assert checked["error"] is None, checked["error"]
    transfers = [s for s in catalog["steps"] if s["operation"] == "transfer"]
    assert len(checked["motions"]) == len(transfers)
    ran = client.post("/api/twins/workflow/run", json={"expected_version": catalog["version"]})
    assert ran.status_code == 200, ran.text


def test_an_example_does_not_replace_instruments_unasked(client):
    _, catalog = add(client, 0, template_id="heater")
    body = {"expected_version": catalog["version"]}
    refused = client.put("/api/twins/examples/flex-reader", json=body)
    assert refused.status_code == 409
    assert len(client.get("/api/twins").json()["twins"]) == 1
    opened = client.put("/api/twins/examples/flex-reader", json={**body, "replace": True})
    assert opened.status_code == 200 and len(opened.json()["twins"]) == 3
    version = opened.json()["version"]
    missing = client.put("/api/twins/examples/nope", json={"expected_version": version})
    assert missing.status_code == 404
