from test_instruments import add, confirm
from test_layout_constraints import twin_spec


def basis(catalog, twin_id):
    return next(t for t in catalog["twins"] if t["id"] == twin_id)["size_basis"]


def check(client, twin_id, version, checked=True):
    return client.put(
        f"/api/twins/{twin_id}/size-check",
        json={"expected_version": version, "checked": checked},
    )


def test_a_library_footprint_is_catalogued_until_its_parts_are_edited(client):
    ot2, catalog = add(client, 0, workcell_id="opentrons-ot2")
    assert basis(catalog, ot2) == "catalogued"
    catalog = confirm(client, ot2, catalog["version"], twin_spec(catalog, ot2))
    assert basis(catalog, ot2) == "catalogued"
    # Renaming changes nothing about the dimensions; resizing a part does.
    spec = {**twin_spec(catalog, ot2), "name": "Our OT-2"}
    catalog = confirm(client, ot2, catalog["version"], spec)
    assert basis(catalog, ot2) == "catalogued"
    part = spec["parts"][0]
    resized = [{**part, "size": [part["size"][0] + 0.05, *part["size"][1:]]}, *spec["parts"][1:]]
    catalog = confirm(client, ot2, catalog["version"], {**spec, "parts": resized})
    assert basis(catalog, ot2) == "estimated"


def test_a_template_is_estimated_until_the_learner_checks_it(client):
    heater, catalog = add(client, 0, template_id="heater")
    assert basis(catalog, heater) == "estimated"
    assert check(client, heater, catalog["version"]).status_code == 409  # not confirmed yet
    catalog = confirm(client, heater, catalog["version"], twin_spec(catalog, heater))
    response = check(client, heater, catalog["version"])
    assert response.status_code == 200, response.text
    catalog = response.json()
    assert basis(catalog, heater) == "checked"
    assert check(client, heater, catalog["version"] - 1).status_code == 409  # stale command
    catalog = check(client, heater, catalog["version"], False).json()
    assert basis(catalog, heater) == "estimated"


def test_resizing_a_checked_twin_clears_the_check(client):
    ot2, catalog = add(client, 0, workcell_id="opentrons-ot2")
    catalog = confirm(client, ot2, catalog["version"], twin_spec(catalog, ot2))
    catalog = check(client, ot2, catalog["version"]).json()
    assert basis(catalog, ot2) == "checked"
    spec = twin_spec(catalog, ot2)
    part = spec["parts"][0]
    resized = [{**part, "size": [part["size"][0] + 0.05, *part["size"][1:]]}, *spec["parts"][1:]]
    catalog = confirm(client, ot2, catalog["version"], {**spec, "parts": resized})
    assert basis(catalog, ot2) == "estimated"
