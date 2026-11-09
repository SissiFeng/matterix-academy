from academy.workcell_layout import access
from test_instruments import add, confirm, plan
from test_layout import BENCH, placed_cell, preview


def twin_spec(catalog, twin_id):
    return next(t for t in catalog["twins"] if t["id"] == twin_id)["spec"]


def deck_cell(client):
    """The meeting case: an OT-2 and a Flex, a UR5e between them, two plates on each."""
    ot2, catalog = add(client, 0, workcell_id="opentrons-ot2")
    catalog = confirm(client, ot2, catalog["version"], twin_spec(catalog, ot2))
    flex, catalog = add(client, catalog["version"], chemlab_id="opentrons_flex_single_5_1000ul")
    catalog = confirm(client, flex, catalog["version"], twin_spec(catalog, flex))
    arm, catalog = add(client, catalog["version"], template_id="transfer-arm")
    catalog = confirm(client, arm, catalog["version"], twin_spec(catalog, arm))
    steps = [
        {"device_id": ot2, "operation": "load", "value": 200, "sample": "plate-a"},
        {"device_id": ot2, "operation": "load", "value": 200, "sample": "plate-b"},
        {"device_id": flex, "operation": "load", "value": 200, "sample": "plate-c"},
        {"device_id": flex, "operation": "load", "value": 200, "sample": "plate-d"},
        {"device_id": ot2, "operation": "mix", "value": 5, "sample": "plate-a"},
        {
            "device_id": arm,
            "operation": "transfer",
            "source_id": ot2,
            "target_id": flex,
            "sample": "plate-a",
        },
    ]
    response = plan(client, catalog["version"], steps)
    assert response.status_code == 200, response.text
    return ot2, flex, arm, response.json()


def constrain(client, version, constraints):
    response = client.put(
        "/api/twins/layout/constraints",
        json={"expected_version": version, "constraints": constraints},
    )
    assert response.status_code == 200, response.text
    return response.json()


def search(client, **body):
    response = client.post("/api/twins/layout/search", json={"bench": BENCH, **body})
    assert response.status_code == 200, response.text
    return response.json()


def test_arm_reaches_two_slots_on_each_liquid_handler(client, monkeypatch):
    from academy import layout_search

    monkeypatch.setattr(layout_search, "CHUNK_PLANS", 3)
    ot2, flex, arm, catalog = deck_cell(client)
    catalog = constrain(
        client,
        catalog["version"],
        [
            {"kind": "reach_slots", "twin_id": ot2, "count": 2},
            {"kind": "reach_slots", "twin_id": flex, "count": 2},
        ],
    )
    assert len(catalog["constraints"]) == 2
    found = search(client)
    assert found["candidates"], found["diagnosis"]
    option = found["candidates"][0]
    assert len(option["slots"][ot2]) >= 2 and len(option["slots"][flex]) >= 2
    # The planned transfer uses the slots the mock contract assigned.
    [motion] = option["motions"]
    assert (motion["source_site"], motion["target_site"]) == ("1", "D3")
    checked = preview(client, option["layout"]["placements"])
    assert checked["error"] is None


def test_slot_moves_the_grasp_point(client):
    ot2, flex, arm, catalog = deck_cell(client)
    spec = twin_spec(catalog, ot2)
    placement = {"x": 0.0, "z": 0.0, "yaw": 0, "access": "top"}
    assert access(spec, placement, "1")[0] != access(spec, placement, "9")[0]


def test_zone_and_distance_preferences_hold(client, monkeypatch):
    from academy import layout_search

    monkeypatch.setattr(layout_search, "CHUNK_PLANS", 2)
    reader, heater, arm, _, catalog = placed_cell(client)
    catalog = constrain(
        client,
        catalog["version"],
        [
            {"kind": "zone", "twin_id": reader, "side": "right"},
            {"kind": "apart", "twin_id": reader, "other_id": heater, "metres": 0.6},
        ],
    )
    found = search(client)
    assert found["candidates"]
    for option in found["candidates"]:
        rows = {p["twin_id"]: p for p in option["layout"]["placements"]}
        assert rows[reader]["x"] > -0.35  # centre right of the middle, within a footprint


def test_impossible_preferences_are_diagnosed(client):
    reader, heater, arm, _, catalog = placed_cell(client)
    constrain(
        client,
        catalog["version"],
        [{"kind": "near", "twin_id": reader, "other_id": heater, "metres": 0.05}],
    )
    found = search(client)
    assert found["candidates"] == []
    kinds = [d["kind"] for d in found["diagnosis"]]
    assert "constraint" in kinds
    hint = next(d for d in found["diagnosis"] if d["kind"] == "constraint")["hint"]
    assert "within 0.05 m" in hint


def test_tiny_bench_points_at_room(client):
    placed_cell(client)
    found = search(client, bench={"width": 0.8, "depth": 0.6})
    assert found["diagnosis"][0]["kind"] in {"room", "reach"}
    assert "bench" in " ".join(d["hint"] for d in found["diagnosis"])


def test_used_instrument_cannot_be_excluded(client):
    reader, heater, arm, _, catalog = placed_cell(client)
    constrain(client, catalog["version"], [{"kind": "exclude", "twin_id": reader}])
    response = client.post("/api/twins/layout/search", json={"bench": BENCH})
    assert response.status_code == 422
    assert "has to be on the bench" in response.json()["detail"]["message"]


def test_constraint_shape_is_checked(client):
    reader, heater, arm, _, catalog = placed_cell(client)
    bad = client.put(
        "/api/twins/layout/constraints",
        json={
            "expected_version": catalog["version"],
            "constraints": [{"kind": "near", "twin_id": reader}],
        },
    )
    assert bad.status_code == 422


def test_consolidation_offers_a_shared_deck(client, monkeypatch):
    from academy import layout_search

    monkeypatch.setattr(layout_search, "CHUNK_PLANS", 1)
    ot2, flex, arm, catalog = deck_cell(client)
    found = search(client)
    pairs = {(c["drop_id"], c["into_id"]) for c in found["consolidation"]}
    assert (ot2, flex) in pairs and (flex, ot2) in pairs
    into_flex = next(c for c in found["consolidation"] if c["drop_id"] == ot2)
    # Plates a and b join c and d on the Flex: one more slot than its peak of three.
    assert into_flex["transfers_saved"] == 1 and into_flex["extra_slots"] == 1
    assert "more slots" in into_flex["message"]
