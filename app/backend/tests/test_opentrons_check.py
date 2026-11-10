from academy import opentrons_check
from academy.models import Experiment


def plan(actions, **fields):
    return Experiment(
        course_id="workflow-sandbox",
        actions=[{"kind": k, "well": w, "volume": v} for k, w, v in actions],
        **fields,
    ).model_dump()


def messages(found):
    return [(item["step"], item["message"]) for item in found]


def test_a_clean_transfer_passes_and_becomes_a_protocol():
    experiment = plan(
        [
            ("pickup", "stock", 100),
            ("aspirate", "stock", 100),
            ("dispense", "A1", 100),
            ("drop", "stock", 100),
        ],
        title='Ada\'s "first" transfer',
    )
    result = opentrons_check.check(experiment)
    assert result["stops"] == [] and result["unnoticed"] == []
    assert result["robot"] == "Flex" and result["evidence"] == "synthetic"
    source = opentrons_check.protocol(experiment)
    assert '"robotType": "Flex"' in source and "ctx.load_waste_chute()" in source
    assert 'pipette.aspirate(100, stock["A1"])' in source
    assert 'pipette.dispense(100, plate["A1"])' in source
    scope = {}
    exec(source, scope)  # the learner's title cannot break out of the metadata
    assert scope["metadata"]["protocolName"] == 'Ada\'s "first" transfer'


def test_tip_and_pipette_errors_stop_the_run_like_the_simulator():
    result = opentrons_check.check(
        plan(
            [
                ("aspirate", "stock", 100),  # no tip
                ("pickup", "stock", 100),
                ("pickup", "stock", 100),  # tip already attached
                ("aspirate", "stock", 300),
                ("aspirate", "stock", 50),  # p300 is full
                ("dispense", "A1", 200),
                ("dispense", "A2", 200),  # only 100 left
            ],
            instrument="ot2",
            layout={"stock": "1", "plate": "2", "tips": "3", "waste": "12"},
        )
    )
    assert [step for step, _ in messages(result["stops"])] == [1, 3, 5, 7]
    assert "no tip attached" in result["stops"][0]["message"]
    assert "room for 0 µL" in result["stops"][2]["message"]
    assert "tip holds 100 µL" in result["stops"][3]["message"]


def test_mistakes_the_simulator_runs_anyway_are_reported_separately():
    result = opentrons_check.check(
        plan(
            [
                ("pickup", "stock", 100),
                ("aspirate", "stock", 2),  # below the 1000 µL pipette's 5 µL
                ("dispense", "A1", 2),
                ("aspirate", "stock", 300),  # the stock only holds 100
                ("drop", "stock", 100),  # liquid still in the tip
                ("pickup", "stock", 100),
            ],
            source_volume=100,
        )
    )
    assert result["stops"] == []
    found = messages(result["unnoticed"])
    assert [step for step, _ in found] == [2, 3, 4, 5, None]
    assert "below the 5 µL" in found[0][1] and "which holds 98 µL" in found[2][1]
    assert "300 µL still in it" in found[3][1] and "tip still on" in found[4][1]


def test_routes_check_the_owner_and_refuse_a_protocol_that_would_stop(client):
    good = client.post(
        "/api/sessions",
        json={
            "course_id": "workflow-sandbox",
            "instrument": "ot2",
            "layout": {"stock": "1", "plate": "2", "tips": "3", "waste": "12"},
        },
    ).json()
    path = f"/api/sessions/{good['id']}"
    assert client.get(f"{path}/opentrons-check").json()["robot"] == "OT-2"
    protocol = client.get(f"{path}/opentrons-protocol")
    assert protocol.status_code == 200 and "p300_single_gen2" in protocol.text
    assert "attachment" in protocol.headers["content-disposition"]

    bad = {**good["experiment"], "actions": [{"kind": "aspirate", "well": "stock", "volume": 50}]}
    saved = client.put(path, json={"version": good["version"], "experiment": bad})
    assert saved.status_code == 200
    assert client.get(f"{path}/opentrons-check").json()["stops"][0]["step"] == 1
    assert client.get(f"{path}/opentrons-protocol").status_code == 409
