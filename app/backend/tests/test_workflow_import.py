from copy import deepcopy

import pytest
from academy.workflow_brief import Draft
from test_instruments import add, confirm
from test_layout_constraints import twin_spec

# An orchestrator-neutral workflow file: two plates on each liquid handler, the arm
# must reach two slots on both, and the handlers stand apart.
FILE = {
    "roles": [
        {
            "key": "ot2",
            "name": "Liquid handler A",
            "operations": ["load", "mix"],
            "vessel": "plate",
            "query": "OT-2",
            "reach_slots": 2,
        },
        {
            "key": "flex",
            "name": "Liquid handler B",
            "operations": ["load", "mix"],
            "vessel": "plate",
            "query": "Flex",
            "reach_slots": 2,
        },
        {
            "key": "arm",
            "name": "Robot arm",
            "operations": ["transfer"],
            "vessel": "none",
            "query": "robot arm",
            "reach_slots": 0,
        },
    ],
    "steps": [
        {
            "role": r,
            "operation": "load",
            "source_role": "",
            "target_role": "",
            "value": 200,
            "sample": s,
        }
        for r, s in [
            ("ot2", "plate-a"),
            ("ot2", "plate-b"),
            ("flex", "plate-c"),
            ("flex", "plate-d"),
        ]
    ]
    + [
        {
            "role": "arm",
            "operation": "transfer",
            "source_role": "ot2",
            "target_role": "flex",
            "value": 1,
            "sample": "plate-a",
        }
    ],
    "assumptions": [],
    "preferences": [
        {"kind": "apart", "role": "ot2", "other_role": "flex", "side": "", "metres": 0.5},
        {"kind": "zone", "role": "ot2", "other_role": "", "side": "left", "metres": 0.5},
    ],
}


def test_imported_file_binds_into_steps_and_layout_constraints(client):
    catalog = client.get("/api/twins").json()
    response = client.post(
        "/api/twins/workflow/brief/import",
        json={"expected_version": catalog["version"], "name": "From Ouroboros", "draft": FILE},
    )
    assert response.status_code == 200, response.text
    catalog = response.json()
    assert catalog["brief"]["status"] == "draft" and catalog["brief"]["source"] == "import"
    ids = {}
    for role, source in [
        ("ot2", {"workcell_id": "opentrons-ot2"}),
        ("flex", {"chemlab_id": "opentrons_flex_single_5_1000ul"}),
        ("arm", {"template_id": "transfer-arm"}),
    ]:
        ids[role], catalog = add(client, catalog["version"], **source)
        catalog = confirm(client, ids[role], catalog["version"], twin_spec(catalog, ids[role]))
        catalog = client.put(
            "/api/twins/workflow/brief/bind",
            json={"expected_version": catalog["version"], "role": role, "twin_id": ids[role]},
        ).json()
    response = client.put(
        "/api/twins/workflow/brief/apply", json={"expected_version": catalog["version"]}
    )
    assert response.status_code == 200, response.text
    catalog = response.json()
    assert [s["sample"] for s in catalog["steps"]][:4] == [
        "plate-a",
        "plate-b",
        "plate-c",
        "plate-d",
    ]
    kinds = sorted((c["kind"], c["twin_id"]) for c in catalog["constraints"])
    assert kinds == sorted(
        [
            ("reach_slots", ids["ot2"]),
            ("reach_slots", ids["flex"]),
            ("apart", ids["ot2"]),
            ("zone", ids["ot2"]),
        ]
    )


def test_schema_endpoint_matches_the_draft_model(client):
    schema = client.get("/api/twins/workflow/brief/schema").json()
    assert schema["$id"].startswith("matterix-academy/workflow-draft")
    assert "preferences" in schema["required"]


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda d: d["preferences"].append({**d["preferences"][1], "side": ""}), "needs a side"),
        (lambda d: d["roles"][2].update(reach_slots=2), "holds no samples"),
        (
            lambda d: d["preferences"].append({**d["preferences"][0], "other_role": "ot2"}),
            "two different",
        ),
    ],
)
def test_bad_files_are_rejected(change, message):
    bad = deepcopy(FILE)
    change(bad)
    with pytest.raises(ValueError, match=message):
        Draft.model_validate(bad)


def test_bad_import_is_a_422_and_saves_nothing(client):
    bad = deepcopy(FILE)
    bad["steps"][4]["target_role"] = "ot2"
    response = client.post(
        "/api/twins/workflow/brief/import", json={"expected_version": 0, "draft": bad}
    )
    assert response.status_code == 422
    assert client.get("/api/twins").json()["brief"] is None
