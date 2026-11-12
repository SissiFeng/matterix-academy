"""Where labware goes into an instrument, and what the arm must stay clear of on the way."""

import time

from academy import chemlab, workcell_models
from academy import workcell_layout as wl
from academy.collision import shapes
from academy.simple_twins import TEMPLATES, loaded
from test_instruments import add, confirm, plan
from test_layout import preview, search
from test_layout_constraints import twin_spec

FLEX = "opentrons_flex_single_5_1000ul"
READER = "bmg_clariostarplus"
BENCH = {"width": 2.4, "depth": 1.6}


def user_cell(client):
    """A Flex, a UR5e and a plate reader from the library, as a learner adds them."""
    flex, catalog = add(client, 0, chemlab_id=FLEX)
    catalog = confirm(client, flex, catalog["version"], twin_spec(catalog, flex))
    arm, catalog = add(client, catalog["version"], workcell_id="ur5e-2f140")
    catalog = confirm(client, arm, catalog["version"], twin_spec(catalog, arm))
    reader, catalog = add(client, catalog["version"], chemlab_id=READER)
    catalog = confirm(client, reader, catalog["version"], twin_spec(catalog, reader))
    steps = [
        {"device_id": flex, "operation": "load", "value": 150},
        {"device_id": flex, "operation": "mix", "value": 1},
        {"device_id": arm, "operation": "transfer", "source_id": flex, "target_id": reader},
        {"device_id": reader, "operation": "read"},
    ]
    response = plan(client, catalog["version"], steps)
    assert response.status_code == 200, response.text
    return flex, arm, reader, response.json()


def test_library_instruments_say_where_labware_goes_in():
    flex = chemlab.CHEMLAB[FLEX]["spec"]
    assert (flex["access"], flex["level_m"]) == ("front", 0.153)
    assert chemlab.CHEMLAB[READER]["spec"]["access"] == "front"
    assert chemlab.CHEMLAB["ika_plate_rctdigital"]["spec"]["access"] == "top"
    ot2 = workcell_models.catalog()["opentrons-ot2"]["spec"]
    assert (ot2["access"], ot2["level_m"]) == ("front", 0.1)
    assert TEMPLATES["reader"]["access"] == "front"
    # The arm stands on the bench: its base is a plate, not a pedestal.
    for arm in (workcell_models.catalog()["ur5e-2f140"]["spec"], TEMPLATES["transfer-arm"]):
        assert wl.top(arm) < 0.05


def test_a_deck_is_served_under_its_enclosure_and_a_reader_on_its_tray():
    flex = chemlab.CHEMLAB[FLEX]["spec"]
    placement = {"x": 0.0, "z": 0.0, "yaw": 0, "access": "top"}
    point, direction, rotation, reach = wl.access(flex, placement, "D1")
    # Just above the deck, far below the roof, and left up and out through the front.
    assert abs(point[1] - 0.173) < 1e-9 and wl.top(flex) > 0.8
    assert direction[1] > 0 and direction[2] > 0 and rotation[2] == (0.0, -1.0, 0.0)
    out = [point[i] + direction[i] * reach for i in range(3)]
    assert out[2] > wl.footprint(flex)[3]
    reader = chemlab.CHEMLAB[READER]["spec"]
    point, direction, _, _ = wl.access(reader, placement)
    assert point[2] > wl.footprint(reader)[3] and point[1] < wl.top(reader) / 2
    assert direction == (0.0, 1.0, 0.0)
    # A twin that says where labware goes in is served there, whatever was saved.
    assert wl.side(reader, placement) == "front"
    assert wl.side(chemlab.CHEMLAB["ika_ks4000"]["spec"], {**placement, "access": "front"}) == "top"
    assert wl.side(TEMPLATES["heater"], {**placement, "access": "front"}) == "front"


def test_a_measured_model_keeps_its_openings():
    entry = chemlab.CHEMLAB[FLEX]
    twin = {"id": "f", "source": "chemlab_asset", "asset": {"id": FLEX}, "spec": entry["spec"]}
    boxes = shapes(twin)
    assert len(boxes) > 5

    def solid(x, y, z):
        return any(
            all(abs(p - c) <= h for p, c, h in zip((x, y, z), *box, strict=True)) for box in boxes
        )

    x0, x1, z0, z1 = wl.footprint(entry["spec"])
    # The base and the roof are solid; the space over the deck is open, from the front in.
    assert solid(0, 0.02, 0) and solid(-0.1, wl.top(entry["spec"]) - 0.02, z0 + 0.02)
    assert not any(solid(-0.06, 0.4, z) for z in (z1 - 0.01, 0.2, 0.03))
    # Without a measured model the twin is its own box.
    assert len(shapes({"id": "h", "source": "template", "spec": TEMPLATES["heater"]})) == 2


def test_twins_stored_before_this_take_it_up_on_read():
    entry = workcell_models.catalog()["ur5e-2f140"]
    old = {k: v for k, v in entry["spec"].items() if k not in ("access", "level_m")}
    old["parts"] = [{**old["parts"][0], "size": [0.16, 0.5775, 0.16], "position": [0, 0.28875, 0]}]
    twin = {"id": "a", "source": "workcell_asset", "asset": {"id": "ur5e-2f140"}, "spec": old}
    assert wl.top(loaded(twin)["spec"]) < 0.05
    # A size the learner set themselves stays.
    kept = loaded({**twin, "size_edited": True})["spec"]
    assert wl.top(kept) > 0.5 and kept["access"] == "top"
    flex = {k: v for k, v in chemlab.CHEMLAB[FLEX]["spec"].items() if k != "access"}
    twin = {"id": "f", "source": "chemlab_asset", "asset": {"id": FLEX}, "spec": flex}
    assert loaded(twin)["spec"]["access"] == "front"
    assert loaded(loaded(twin)) == loaded(twin)


def test_the_arm_takes_a_plate_from_the_flex_deck_to_the_reader_tray(client, monkeypatch):
    from academy import layout_search

    monkeypatch.setattr(layout_search, "CHUNK_PLANS", 3)
    monkeypatch.setattr(layout_search, "CHUNK_SECONDS", 120.0)
    flex, arm, reader, catalog = user_cell(client)
    began = time.monotonic()
    found = search(client, bench=BENCH)
    assert found["candidates"], found["diagnosis"]
    # Measured shapes must not make a search chunk slow.
    assert time.monotonic() - began < 30
    rows = found["candidates"][0]["layout"]["placements"]
    assert {p["twin_id"]: p["access"] for p in rows if p["twin_id"] != arm} == {
        flex: "front",
        reader: "front",
    }
    checked = preview(client, rows, bench=BENCH)
    assert checked["error"] is None, checked["error"]
    [motion] = checked["motions"]
    tips = [frame[-1] for frame in motion["frames"]]
    twins = {t["id"]: t["spec"] for t in catalog["twins"]}
    # Every kept frame says how far along it is, what it is doing and how clear the arm is.
    profile = motion["profile"]
    assert {len(v) for k, v in profile.items() if k != "segments"} == {len(motion["frames"])}
    assert profile["progress"][0] == 0 and profile["progress"][-1] == 1
    assert profile["progress"] == sorted(profile["progress"])
    assert profile["segments"][2].startswith("Transit to Plate reader")
    assert sorted(set(profile["segment"])) == [0, 1, 2, 3, 4]
    assert min(profile["clearance_m"]) >= wl.SAFETY and all(profile["nearest"])
    # The workflow is laid out in time: the transfer lasts as long as its arm path.
    steps = checked["timeline"]
    assert [s["operation"] for s in steps] == ["load", "mix", "transfer", "read"]
    assert steps[0]["start_s"] == 0 and steps[2]["start_s"] == steps[1]["end_s"]
    assert round(steps[2]["end_s"] - steps[2]["start_s"], 1) == motion["seconds"]
    assert steps[1]["samples"]["sample"]["location"] == flex
    assert steps[2]["samples"]["sample"]["location"] == reader
    # It dips to the deck first and to the tray last, and never goes over the Flex's roof.
    third = len(tips) // 3
    assert min(t[1] for t in tips[:third]) < 0.2
    assert min(t[1] for t in tips[-third:]) < wl.top(twins[reader]) / 2
    assert max(t[1] for t in tips) < wl.top(twins[flex])
