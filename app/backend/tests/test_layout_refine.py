"""A layout is changed by asking in plain words; a model only names the changes."""

from academy import layout_refine
from botocore.exceptions import ClientError
from test_workflow_brief import nova

FLEX, READER, ARM = "Liquid handler (Opentrons Flex)", "Plate reader (CLARIOstar Plus)", "UR5e arm"


def change(kind, instrument="", **fields):
    return {"kind": kind, "instrument": instrument, **fields}


def opened(client):
    catalog = client.put("/api/twins/examples/flex-reader", json={"expected_version": 0}).json()
    ids = {t["spec"]["name"]: t["id"] for t in catalog["twins"]}
    return catalog, ids


def refine(client, catalog, text="Put the reader on the right, closer to the Flex."):
    return client.post("/api/twins/layout/refine", json={**catalog["layout"], "text": text})


def test_without_a_model_the_request_is_refused(client):
    catalog, _ = opened(client)
    assert refine(client, catalog).status_code == 503


def test_a_request_becomes_preferences_moves_and_a_bench(client, app):
    catalog, ids = opened(client)
    fake = nova(
        app,
        {
            "changes": [
                change("zone", READER, side="right"),
                change("near", READER, other=FLEX, metres=0.6),
                change("move", ARM, side="left", metres=0.1),
                change("turn", FLEX, turns=1),
                change("keep", FLEX),
                change("bench", width=3, depth=0),
                change("zone", "Centrifuge", side="left"),
                change("near", READER, other=READER, metres=0.5, side=None),
            ],
            "unclear": "the colour of the bench",
        },
    )
    answer = refine(client, catalog)
    assert answer.status_code == 200, answer.text
    result = answer.json()
    # The model saw the instruments, where they are, and the request.
    sent = fake.calls[0]["messages"][0]["content"][0]["text"]
    assert f"- {READER}: x -0.7, z 0.21, turned 90°" in sent and sent.endswith("to the Flex.")
    assert result["constraints"] == [
        {"kind": "zone", "twin_id": ids[READER], "side": "right"},
        {"kind": "near", "twin_id": ids[READER], "other_id": ids[FLEX], "metres": 0.6},
    ]
    places = {p["twin_id"]: p for p in result["placements"]}
    assert (places[ids[ARM]]["x"], places[ids[ARM]]["kept"]) == (-0.1, True)
    assert (places[ids[FLEX]]["yaw"], places[ids[FLEX]]["kept"]) == (0, True)
    assert result["bench"] == {"width": 3, "depth": 1.6}
    assert result["search"] is True and result["model"] == "Amazon Nova Pro"
    assert result["applied"] == [
        f"{READER} on the right",
        f"{READER} within 0.6 m of {FLEX}",
        f"{ARM} moved 0.1 m toward the left",
        f"{FLEX} turned 1 quarter turn(s)",
        f"{FLEX} stays where it is",
        "Bench 3 × 1.6 m",
    ]
    assert result["skipped"] == ["Centrifuge", f"{READER} (near)"]
    assert result["unclear"] == "the colour of the bench"
    # Nothing was saved: the learner reviews the draft first.
    after = client.get("/api/twins").json()
    assert after["version"] == catalog["version"] and after["layout"] == catalog["layout"]
    # The preferences are ones the layout search accepts.
    saved = client.put(
        "/api/twins/layout/constraints",
        json={"expected_version": after["version"], "constraints": result["constraints"]},
    )
    assert saved.status_code == 200, saved.text


def test_a_new_preference_replaces_the_one_it_contradicts():
    twins = [{"id": "a", "spec": {"name": "A"}}, {"id": "b", "spec": {"name": "B"}}]
    before = [
        {"kind": "zone", "twin_id": "a", "side": "left"},
        {"kind": "apart", "twin_id": "b", "other_id": "a", "metres": 1},
    ]
    changes = layout_refine.parse(
        {"changes": [change("zone", "a", side="right"), change("near", "A", other="B", metres=0.4)]}
    ).model_dump()["changes"]
    result = layout_refine.apply(changes, twins, {"width": 2, "depth": 1}, [], before)
    assert result["constraints"] == [
        {"kind": "zone", "twin_id": "a", "side": "right"},
        {"kind": "near", "twin_id": "a", "other_id": "b", "metres": 0.4},
    ]
    # A request with only moves needs no new search.
    place = {"twin_id": "a", "x": 0.0, "z": 0.0, "yaw": 0, "access": "top", "kept": False}
    move = layout_refine.parse({"changes": [change("move", "A", side="front", metres=0.2)]})
    moved = layout_refine.apply(
        move.model_dump()["changes"], twins, {"width": 2, "depth": 1}, [place], before
    )
    assert moved["search"] is False and moved["placements"][0]["z"] == 0.2
    assert moved["constraints"] == before
    # A seventeenth preference is refused by name; none is dropped to make room.
    full = [{"kind": "zone", "twin_id": str(i), "side": "left"} for i in range(16)]
    zone = layout_refine.parse({"changes": [change("zone", "A", side="right")]})
    kept = layout_refine.apply(
        zone.model_dump()["changes"], twins, {"width": 2, "depth": 1}, [], full
    )
    assert kept["constraints"] == full and kept["skipped"] == ["A (zone): 16 preferences at most"]


def test_an_unusable_answer_is_reported_not_applied(client, app):
    catalog, _ = opened(client)
    nova(app, {"changes": [{"kind": "teleport", "instrument": FLEX}], "unclear": ""})
    answer = refine(client, catalog)
    assert answer.status_code == 502 and "Rephrase" in answer.json()["detail"]
    # A model that does not answer at all is an error too, not an empty set of changes.
    nova(
        app, ClientError({"Error": {"Code": "ThrottlingException", "Message": "busy"}}, "Converse")
    )
    assert refine(client, catalog).status_code == 502
    after = client.get("/api/twins").json()
    assert after["version"] == catalog["version"] and after["layout"] == catalog["layout"]
