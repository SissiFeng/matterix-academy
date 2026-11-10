import pytest
from academy import workcell_layout as wl
from academy.decks import deck_sites
from academy.mock_contract import PlanError, execute_mock, transfer_sites
from academy.simple_twins import TEMPLATES, Step, TwinSpec
from academy.workcell_models import catalog


def twin(twin_id, spec):
    return {"id": twin_id, "spec": spec, "confirmed": True, "mode": "mock"}


def ot2():
    return catalog()["opentrons-ot2"]["spec"]


def cell():
    return {
        "ot2": twin("ot2", ot2()),
        "reader": twin("reader", TEMPLATES["reader"]),
        "arm": twin("arm", TEMPLATES["transfer-arm"]),
    }


def test_ot2_and_flex_carry_their_deck_slots():
    spec = ot2()
    assert [s["key"] for s in spec["sites"]][:3] == ["1", "2", "3"]
    assert spec["resource"]["slots"] == len(spec["sites"]) == 11
    flex = deck_sites("flex")
    assert {s["key"] for s in flex} >= {"D1", "A1", "C2"}
    # Front row (1, D) sits toward +z, the front of the twin.
    assert spec["sites"][0]["z"] > spec["sites"][-1]["z"]


def test_slot_count_must_match_drawn_slots():
    spec = {**ot2(), "resource": {"slots": 4}}
    with pytest.raises(ValueError, match="drawn slots"):
        TwinSpec.model_validate(spec)


def test_several_samples_take_separate_slots():
    twins = cell()
    steps = [
        {"device_id": "ot2", "operation": "load", "value": 100, "sample": "plate-a"},
        {"device_id": "ot2", "operation": "load", "value": 100, "sample": "plate-b", "site": "5"},
        {"device_id": "ot2", "operation": "mix", "value": 5, "sample": "plate-b"},
        {
            "device_id": "arm",
            "operation": "transfer",
            "source_id": "ot2",
            "target_id": "reader",
            "sample": "plate-a",
            "value": 1,
        },
        {"device_id": "reader", "operation": "read", "value": 1, "sample": "plate-a"},
    ]
    trace = execute_mock(twins, steps)
    assert trace[0]["site"] == "1" and trace[1]["site"] == "5"
    assert trace[3]["source_site"] == "1" and trace[3]["location"] == "reader"
    assert trace[-1]["samples"]["plate-b"]["mixed"] is True
    assert trace[-1]["samples"]["plate-a"]["mixed"] is False
    assert transfer_sites(twins, steps) == {4: ("1", "1")}


def test_full_instrument_and_busy_slot_are_rejected():
    twins = cell()
    load = {"device_id": "reader", "operation": "load", "value": 100}
    with pytest.raises(PlanError, match="no free slot for plate-b"):
        execute_mock(twins, [{**load, "sample": "plate-a"}, {**load, "sample": "plate-b"}])
    with pytest.raises(PlanError, match="already holds plate-a"):
        execute_mock(
            twins,
            [
                {
                    "device_id": "ot2",
                    "operation": "load",
                    "value": 1,
                    "sample": "plate-a",
                    "site": "2",
                },
                {
                    "device_id": "ot2",
                    "operation": "load",
                    "value": 1,
                    "sample": "plate-b",
                    "site": "2",
                },
            ],
        )
    with pytest.raises(PlanError, match="no slot 12"):
        execute_mock(twins, [{"device_id": "ot2", "operation": "load", "value": 1, "site": "12"}])


def test_default_sample_keeps_single_sample_messages():
    twins = cell()
    load = {"device_id": "ot2", "operation": "load", "value": 1}
    with pytest.raises(PlanError, match="tracks one sample"):
        execute_mock(twins, [load, load])


def test_step_fields_belong_to_their_operation():
    with pytest.raises(ValueError, match="Only a load"):
        Step(device_id="0" * 32, operation="mix", site="3")
    with pytest.raises(ValueError, match="Only transfers"):
        Step(device_id="0" * 32, operation="mix", target_site="3")


def test_top_access_reaches_the_named_slot():
    spec = ot2()
    placement = {"x": 0.0, "z": 0.0, "yaw": 0, "access": "top"}
    one = wl.access(spec, placement, "1")[0]
    eleven = wl.access(spec, placement, "11")[0]
    assert one[2] > eleven[2]  # slot 1 is at the front
    assert wl.access(spec, placement)[0][0] == pytest.approx(0.0)
    turned = wl.access(spec, {**placement, "yaw": 90}, "1")[0]
    assert turned[0] == pytest.approx(one[2], abs=1e-6)


def test_library_points_to_lessons_first_when_searching():
    from academy.library import search

    assert search("OT-2")["results"][0]["lesson"] == "ot2"
    flex = search("opentrons flex")["results"][0]
    assert (flex["id"], flex["lesson"]) == ("opentrons_flex_single_5_1000ul", "flex")
    assert search("xpr204e")["results"][0]["lesson"] is None
