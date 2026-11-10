import json
from copy import deepcopy

from academy import workcell_layout as wl
from academy.simple_twins import TEMPLATES
from test_instruments import add, build_cell, confirm, plan

BENCH = {"width": 3.0, "depth": 1.6}


def wall(name, size):
    spec = deepcopy(TEMPLATES["reader"])
    spec["name"] = name
    spec["parts"] = [{"size": size, "position": [0, size[1] / 2, 0], "color": "#222222"}]
    return spec


def placements(reader, heater, arm, **moves):
    rows = {
        arm: {"x": 0, "z": 0, "yaw": 0, "access": "top"},
        heater: {"x": -0.5, "z": 0.1, "yaw": 0, "access": "top"},
        # The reader is turned so its front drawer faces the arm.
        reader: {"x": 0.8, "z": 0.1, "yaw": -90, "access": "front"},
    }
    for twin_id, values in moves.items():
        rows[twin_id] = values
    return [{"twin_id": twin_id, **values} for twin_id, values in rows.items()]


def save_layout(client, version, rows, bench=BENCH):
    return client.put(
        "/api/twins/layout",
        json={"expected_version": version, "bench": bench, "placements": rows},
    )


def preview(client, rows, bench=BENCH):
    response = client.post("/api/twins/layout/preview", json={"bench": bench, "placements": rows})
    assert response.status_code == 200, response.text
    return response.json()


def workflow(reader, heater, arm):
    return [
        {"device_id": heater, "operation": "load", "value": 150},
        {"device_id": arm, "operation": "transfer", "source_id": heater, "target_id": reader},
        {"device_id": reader, "operation": "read"},
    ]


def placed_cell(client, extra=()):
    reader, heater, arm, catalog = build_cell(client)
    extras = []
    for name, size in extra:
        twin_id, catalog = add(client, catalog["version"], template_id="reader")
        catalog = confirm(client, twin_id, catalog["version"], wall(name, size))
        extras.append(twin_id)
    response = plan(client, catalog["version"], workflow(reader, heater, arm))
    assert response.status_code == 200, response.text
    return reader, heater, arm, extras, response.json()


def assert_clear(catalog, rows, motion):
    """Re-measure every emitted frame against the placed boxes, outside the planner."""
    twins = {t["id"]: t for t in catalog["twins"]}
    layout = {"bench": BENCH, "placements": rows}
    scene = wl._scene(twins, layout)
    stations = {motion["source_id"], motion["target_id"]}
    for pts in motion["frames"]:
        for index, (_, radius) in enumerate(wl.LINKS):
            a, b = pts[index], pts[index + 1]
            for k in range(41):
                p = [a[i] + (b[i] - a[i]) * k / 40 for i in range(3)]
                assert p[1] - radius > wl.SAFETY - 2e-3
                for box in scene.boxes:
                    if box.twin_id == motion["actor_id"] and index == 0:
                        continue
                    if box.twin_id in stations and index == wl.GRIPPER:
                        continue  # the gripper reaches into the station it serves
                    assert box.distance(p) - radius > wl.SAFETY - 2e-3, (index, box.name)


def test_placed_workflow_gets_a_collision_free_arm_path(client):
    reader, heater, arm, _, catalog = placed_cell(client)
    rows = placements(reader, heater, arm)
    checked = preview(client, rows)
    assert checked["error"] is None
    assert checked["arm"] == "UR5e"
    [motion] = checked["motions"]
    assert motion["step"] == 2 and motion["clearance_m"] >= wl.SAFETY
    assert all(len(pts) == len(wl.LINKS) + 1 for pts in motion["frames"])
    assert_clear(catalog, rows, motion)
    # The same layout always gets the same verdict and path.
    assert preview(client, rows) == checked

    saved = save_layout(client, catalog["version"], rows)
    assert saved.status_code == 200, saved.text
    assert saved.json()["layout"]["placements"][2]["access"] == "front"
    run = client.post("/api/twins/workflow/run", json={"expected_version": saved.json()["version"]})
    assert run.status_code == 200, run.text
    trace = run.json()["runs"][0]["trace"]
    assert trace[1]["motion"]["planner"] in {"swing", "joint", "rrt_connect"}
    assert "frames" not in trace[1]["motion"]  # runs keep only the summary
    assert "motion" not in trace[0]


def test_overlapping_or_off_bench_placements_are_rejected(client):
    reader, heater, arm, _, catalog = placed_cell(client)
    overlap = placements(reader, heater, arm, **{heater: {"x": 0.1, "z": 0, "yaw": 0}})
    response = save_layout(client, catalog["version"], overlap)
    assert response.status_code == 422
    assert response.json()["detail"]["layer"] == "geometry"
    assert "overlaps" in response.json()["detail"]["message"]
    edge = placements(reader, heater, arm, **{heater: {"x": -1.4, "z": 0, "yaw": 0}})
    response = save_layout(client, catalog["version"], edge)
    assert "bench edge" in response.json()["detail"]["message"]
    duplicate = placements(reader, heater, arm) + placements(reader, heater, arm)[:1]
    assert save_layout(client, catalog["version"], duplicate).status_code == 422
    assert client.get("/api/twins").json()["layout"] is None


def test_unreachable_station_blocks_layout_that_would_break_the_workflow(client):
    reader, heater, arm, _, catalog = placed_cell(client)
    far = placements(
        reader, heater, arm, **{reader: {"x": 1.3, "z": 0, "yaw": -90, "access": "front"}}
    )
    checked = preview(client, far)
    assert checked["error"]["layer"] == "geometry"
    assert "Plate reader's front access point" in checked["error"]["message"]
    assert "reaches about 0.85 m" in checked["error"]["message"]
    response = save_layout(client, catalog["version"], far)
    assert response.status_code == 422
    after = client.get("/api/twins").json()
    assert (after["version"], after["layout"]) == (catalog["version"], None)


def test_link_collision_names_the_obstacle_and_returns_the_attempt(client):
    reader, heater, arm, (front, back), catalog = placed_cell(
        client, [("Front shield", [1.4, 1.6, 0.06]), ("Back shield", [1.4, 1.6, 0.06])]
    )
    rows = placements(reader, heater, arm) + [
        {"twin_id": front, "x": 0, "z": 0.42, "yaw": 0, "access": "top"},
        {"twin_id": back, "x": 0, "z": -0.2, "yaw": 0, "access": "top"},
    ]
    checked = preview(client, rows)
    message = checked["error"]["message"]
    assert message.startswith("Step 2: no collision-free path from Heating station to Plate reader")
    assert "shield" in message
    assert checked["blocked"]["blocked_by"].endswith("shield")
    assert checked["blocked"]["frames"]
    # A single shield leaves the long way round, which the planner finds.
    rows = rows[:-1]
    checked = preview(client, rows)
    assert checked["error"] is None, checked["error"]
    assert_clear(client.get("/api/twins").json(), rows, checked["motions"][0])


def test_obstacle_at_an_access_point_is_reported_there(client):
    reader, heater, arm, (screen,), _ = placed_cell(client, [("Screen", [0.06, 0.6, 0.5])])
    rows = placements(reader, heater, arm) + [
        {"twin_id": screen, "x": 0.5, "z": 0.1, "yaw": 0, "access": "top"}
    ]
    error = preview(client, rows)["error"]["message"]
    assert error.startswith("Step 2: Plate reader's front access point")
    assert "Screen" in error


def test_transfers_need_every_station_placed_and_deletion_unplaces(client):
    reader, heater, arm, (spare,), catalog = placed_cell(client, [("Spare", [0.2, 0.2, 0.2])])
    rows = [r for r in placements(reader, heater, arm) if r["twin_id"] != reader]
    checked = preview(client, rows)
    assert checked["error"]["message"] == "Step 2: place Plate reader on the bench in Layout"
    rows = placements(reader, heater, arm) + [
        {"twin_id": spare, "x": -0.5, "z": -0.5, "yaw": 0, "access": "top"}
    ]
    saved = save_layout(client, catalog["version"], rows)
    assert saved.status_code == 200, saved.text
    assert save_layout(client, catalog["version"], rows).status_code == 409
    removed = client.request(
        "DELETE", f"/api/twins/{spare}", json={"expected_version": saved.json()["version"]}
    )
    assert removed.status_code == 200, removed.text
    assert spare not in {p["twin_id"] for p in removed.json()["layout"]["placements"]}


def test_layout_preview_is_owner_scoped(client, app):
    from fastapi.testclient import TestClient

    reader, heater, arm, _, _ = placed_cell(client)
    with TestClient(app) as other:
        other.post("/api/auth/guest", json={"name": "Grace"})
        response = other.post(
            "/api/twins/layout/preview",
            json={"bench": BENCH, "placements": placements(reader, heater, arm)},
        )
        assert response.status_code == 404


def test_saved_layout_fits_storage_and_ik_reaches_random_poses():
    import math
    import random

    base = wl.mount(TEMPLATES["transfer-arm"], {"x": 0.3, "z": -0.2, "yaw": 35})
    rng = random.Random(7)
    for _ in range(40):
        q = [rng.uniform(-math.pi, math.pi) for _ in range(6)]
        q[2] = rng.uniform(-2.8, 2.8)
        tip = wl.frames(q, base)[7]
        target = wl._col(tip, 3)
        rotation = tuple(wl._col(tip, k) for k in range(3))
        solved = next(
            (
                s
                for seed in wl._seeds(base, target)
                if (s := wl.solve_ik(target, rotation, seed, base))
            ),
            None,
        )
        assert solved is not None
        assert wl._norm(wl._sub(wl.points(solved, base)[-1], target)) < 1e-3
    layout = {
        "bench": BENCH,
        "placements": [{"twin_id": "x" * 36, "x": 1.23456, "z": 0, "yaw": 0, "access": "top"}] * 12,
    }
    assert len(json.dumps(layout)) < 2_000


# Grasp-point positions from ur5e-sila-connector@9e6da2e `kinematics.forward(q, tcp=[0, 0, 0.16, 0, 0, 0])`.
CONNECTOR_POSES = [
    ([0, -1.5708, 1.5708, -1.5708, -1.5708, 0], [-0.491899392451, -0.133299046436, 0.327900366219]),
    ([0.4, -2.1, 1.2, 0.3, 1.1, -0.7], [-0.156888442888, -0.338901324137, 0.884933065868]),
    ([-2.5, -0.6, -1.9, 2.2, -0.4, 3.0], [-0.247354705804, 0.280065307334, 0.512071753401]),
]


def test_kinematics_match_the_ur5e_sila_connector():
    identity = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    for joints, expected in CONNECTOR_POSES:
        tip = wl.points(joints, identity)[-1]
        assert max(abs(a - b) for a, b in zip(tip, expected, strict=True)) < 1e-9


def chain(client, step=2, speed=None):
    query = f"step={step}" + (f"&speed={speed}" if speed is not None else "")
    return client.get(f"/api/twins/layout/action-chain?{query}")


def test_saved_transfer_exports_a_connector_action_chain(client):
    reader, heater, arm, _, catalog = placed_cell(client)
    assert chain(client).status_code == 409  # no saved layout yet
    rows = placements(reader, heater, arm)
    saved = save_layout(client, catalog["version"], rows)
    assert saved.status_code == 200, saved.text

    response = chain(client)
    assert response.status_code == 200, response.text
    assert "ur5e-action-chain-step-2.json" in response.headers["content-disposition"]
    doc = response.json()
    assert (doc["schema"], doc["timing_mode"], doc["units"], doc["speed"]) == (
        "ur5e.action-chain/2",
        "automatic",
        "degrees",
        20,
    )
    assert doc["provenance"]["evidence"] == "synthetic"
    assert doc["provenance"]["tcp"] == [0, 0, wl.TOOL, 0, 0, 0]
    waypoints = doc["waypoints"]
    assert 1 <= len(waypoints) <= 24 and len(json.dumps(doc)) < 32_768
    for row in waypoints:
        assert set(row) == {"name", "degrees", "hold"} and 1 <= len(row["name"]) <= 60
        # The connector rejects poses inside its 5° limit margin and never wraps angles.
        assert abs(row["degrees"][2]) < 155 and all(abs(v) < 355 for v in row["degrees"])
        assert 0 < row["hold"] <= 10  # every knot rests, so segments are straight in joint space
    assert [r["name"] for r in waypoints if r["hold"] == wl.DWELL] == [
        "Lower into Heating station",
        "Lower into Plate reader",
    ]

    # Every straight joint segment the connector will interpolate is collision-free.
    twins = {t["id"]: t for t in saved.json()["twins"]}
    planner = wl.Planner(twins, saved.json()["layout"], twins[arm])
    poses = [doc["reference"], *[r["degrees"] for r in waypoints]]
    ignore = {**planner.rest, wl.GRIPPER: {heater, reader}}
    for a, b in zip(poses, poses[1:], strict=False):
        qa, qb = ([wl.math.radians(v) for v in p] for p in (a, b))
        assert planner.edge(qa, qb, ignore, wl.EXPORT_STEP)[0] is not None
    assert chain(client).json() == doc  # deterministic


def test_action_chain_export_rejects_bad_requests(client):
    reader, heater, arm, _, catalog = placed_cell(client)
    save_layout(client, catalog["version"], placements(reader, heater, arm))
    assert chain(client, step=1).json()["detail"]["message"] == "Step 1 is not a transfer"
    assert chain(client, step=9).status_code == 422
    assert chain(client, speed=0).status_code == 422
    assert chain(client, speed=41).status_code == 422
    slow = chain(client, speed=1)
    assert slow.status_code == 422
    assert "the connector allows 120 s per action" in slow.json()["detail"]["message"]


def search(client, bench=BENCH, fixed=(), start=0, avoid=()):
    body = {"bench": bench, "fixed": list(fixed), "start": start, "avoid": list(avoid)}
    response = client.post("/api/twins/layout/search", json=body)
    assert response.status_code == 200, response.text
    return response.json()


METRICS = {"run_s", "arm_s", "path_m", "clearance_m", "reach_margin_m", "area_m2"}


def test_layout_search_returns_measured_layouts_that_carry_the_workflow(client, monkeypatch):
    from academy import layout_search

    monkeypatch.setattr(layout_search, "CHUNK_PLANS", 6)
    reader, heater, arm, (shelf,), catalog = placed_cell(client, [("Shelf", [0.3, 0.4, 0.3])])
    found = search(client)
    assert found["arm"] == "UR5e" and found["total"] > found["next"] > 0
    assert found["candidates"] and found["checked"] <= 6
    # The same chunk always gives the same layouts.
    assert search(client) == found
    for option in found["candidates"]:
        assert METRICS <= option.keys()
        assert option["clearance_m"] >= wl.SAFETY and option["reach_margin_m"] >= 0
        assert option["run_s"] > option["arm_s"] > 0
        rows = option["layout"]["placements"]
        assert {p["twin_id"] for p in rows} == {reader, heater, arm, shelf}
        checked = preview(client, rows)
        assert checked["error"] is None
        [motion] = checked["motions"]
        assert motion["seconds"] == option["arm_s"]
        assert_clear(catalog, rows, motion)
    saved = save_layout(client, catalog["version"], found["candidates"][0]["layout"]["placements"])
    assert saved.status_code == 200, saved.text

    # Resuming skips what was already returned and moves on through the list.
    shown = [c["layout"]["placements"] for c in found["candidates"]]
    more = search(client, start=found["next"], avoid=shown)
    assert more["next"] is None or more["next"] > found["next"]
    search_state = layout_search.Search(
        {t["id"]: t for t in client.get("/api/twins").json()["twins"]},
        BENCH,
        client.get("/api/twins").json()["steps"],
        (),
    )
    for option in more["candidates"]:
        rows = option["layout"]["placements"]
        assert all(search_state.distinct(rows, old) for old in shown)


def test_kept_instruments_stay_where_the_user_put_them(client, monkeypatch):
    from academy import layout_search

    monkeypatch.setattr(layout_search, "CHUNK_PLANS", 4)
    reader, heater, arm, _, _ = placed_cell(client)
    kept = {"twin_id": heater, "x": -0.7, "z": 0.3, "yaw": 0, "access": "top", "kept": True}
    found = search(client, fixed=[kept])
    assert found["candidates"]
    for option in found["candidates"]:
        assert kept in option["layout"]["placements"]
        assert preview(client, option["layout"]["placements"])["error"] is None


def test_layout_search_explains_why_nothing_fits(client):
    reader, heater, arm, _, catalog = placed_cell(client)
    tiny = search(client, bench={"width": 0.8, "depth": 0.6})
    assert tiny["candidates"] == [] and tiny["next"] is None
    assert "fits on the bench" in tiny["failure"]
    overlap = [
        {"twin_id": heater, "x": 0, "z": 0, "yaw": 0, "access": "top"},
        {"twin_id": reader, "x": 0.1, "z": 0, "yaw": 0, "access": "top"},
    ]
    response = client.post("/api/twins/layout/search", json={"bench": BENCH, "fixed": overlap})
    assert response.status_code == 422 and "overlaps" in response.json()["detail"]["message"]
    client.put(
        "/api/twins/workflow",
        json={
            "expected_version": catalog["version"],
            "steps": [{"device_id": heater, "operation": "load"}],
        },
    )
    response = client.post("/api/twins/layout/search", json={"bench": BENCH})
    assert response.status_code == 422 and "transfer step" in response.json()["detail"]["message"]


def test_a_chunk_cut_short_keeps_its_reach_work_so_the_walk_ends(client):
    """A slow host can spend a whole chunk on the first arrangement's reach checks."""
    from academy import layout_search

    placed_cell(client)
    layout_search._reach_memo.clear()
    cell = client.get("/api/twins").json()
    twins = {t["id"]: t for t in cell["twins"]}
    tiny, start = {"width": 0.8, "depth": 0.6}, 0
    for _ in range(200):
        chunk = layout_search.search_layouts(twins, tiny, cell["steps"], start=start, seconds=0.05)
        if chunk["next"] is None:
            break
        start = chunk["next"]
    else:
        raise AssertionError("the search never finished")
    assert chunk["candidates"] == [] and "fits on the bench" in chunk["failure"]
