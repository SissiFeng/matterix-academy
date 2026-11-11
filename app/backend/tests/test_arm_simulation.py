import math
import random

import pytest
from academy import arm_simulation
from academy.arms import ARMS
from academy.mock_contract import PlanError
from academy.workcell_layout import TOOL, frames, mount
from test_layout import placed_cell, placements, preview

PEDESTAL = {"name": "Arm", "parts": [{"position": [0, 0.2, 0], "size": [0.3, 0.4, 0.3]}]}
REST = [0.0, -1.2, 1.6, -1.97, -1.57, 0.0]


def bench(arm="ur5e", obstacle=None):
    twins = {"arm": {"id": "arm", "spec": PEDESTAL}}
    placements = [{"twin_id": "arm", "x": 0.2, "z": -0.1, "yaw": 30, "access": "top"}]
    if obstacle:
        twins["wall"] = {
            "id": "wall",
            "spec": {"name": "Wall", "parts": [{"position": [0, 0.5, 0], "size": obstacle}]},
        }
        placements.append({"twin_id": "wall", "x": 0.2, "z": 0.45, "yaw": 0, "access": "top"})
    layout = {"bench": {"width": 3, "depth": 3}, "placements": placements}
    base = mount(PEDESTAL, placements[0])
    return arm_simulation.Bench.of_layout(twins, layout, twins["arm"], ARMS[arm], base, TOOL), base


def sweep(turn):
    """Joint 1 turning from rest, sampled as the planner samples a path."""
    return [[REST[0] + turn * n / 40, *REST[1:]] for n in range(41)]


@pytest.mark.parametrize("arm", ARMS)
def test_simulated_arm_shares_the_planner_kinematics(arm):
    simulated, base = bench(arm)
    rng = random.Random(7)
    for _ in range(20):
        q = [rng.uniform(-3, 3) for _ in range(6)]
        want = [frames(q, base, ARMS[arm])[6][i][3] for i in range(3)]
        assert math.dist(simulated.flange(q), want) < 1e-4


def test_a_clear_move_is_tracked_within_the_arm_limits():
    simulated, _ = bench()
    result = arm_simulation.simulate(simulated, 1, [("Sweep", sweep(1.5), set())], 20, 2.0)
    # 1.5 rad at 16 °/s cruise is 5.4 s; ramps and the two dwell seconds add the rest.
    assert 7.5 < result["seconds"] < 9.5
    assert result["tracking_deg"] < 1 and result["torque_ratio"] < 1
    assert result["engine"] == "mujoco" and result["nearest"] is None


def test_an_instrument_in_the_way_stops_the_move():
    simulated, _ = bench(obstacle=[0.3, 1.0, 0.3])
    with pytest.raises(PlanError, match="in simulation the .* hits Wall"):
        arm_simulation.simulate(simulated, 3, [("Sweep", sweep(1.5), set())], 20, 2.0)


def test_the_served_station_may_touch_only_the_gripper():
    simulated, _ = bench(obstacle=[0.3, 1.0, 0.3])
    with pytest.raises(PlanError, match="hits Wall"):
        arm_simulation.simulate(simulated, 3, [("Sweep", sweep(1.5), {"wall"})], 20, 2.0)


def test_folding_onto_itself_is_a_collision():
    simulated, _ = bench()
    folded = [0.89, -1.75, 1.88, 2.42, 2.1, 0.36]  # the gripper curled back into the forearm
    fold = [[a + (b - a) * n / 60 for a, b in zip(REST, folded, strict=True)] for n in range(61)]
    with pytest.raises(PlanError, match="hits its own"):
        arm_simulation.simulate(simulated, 1, [("Fold", fold, set())], 20, 2.0)


def test_a_load_beyond_the_rated_torque_is_refused(monkeypatch):
    monkeypatch.setattr(arm_simulation, "PAYLOAD_KG", 300.0)
    simulated, _ = bench()
    with pytest.raises(PlanError, match="rated joint torque"):
        arm_simulation.simulate(simulated, 1, [("Sweep", sweep(1.5), set())], 20, 2.0)


def test_planned_transfers_report_simulated_time_and_clearance(client):
    reader, heater, arm, _, _ = placed_cell(client)
    [motion] = preview(client, placements(reader, heater, arm))["motions"]
    result = motion["simulation"]
    assert result["engine"] == "mujoco"
    assert motion["seconds"] != result["kinematic_seconds"]
    assert result["torque_ratio"] < 1 and result["tracking_deg"] < 2
    assert motion["clearance_m"] >= arm_simulation.SAFETY


def test_a_refused_layout_still_says_it_was_simulated(client, monkeypatch):
    monkeypatch.setattr(arm_simulation, "PAYLOAD_KG", 300.0)
    reader, heater, arm, _, _ = placed_cell(client)
    checked = preview(client, placements(reader, heater, arm))
    assert "rated joint torque" in checked["error"]["message"]
    assert checked["motions"] == [] and checked["simulation"]["engine"] == "mujoco"


def test_without_mujoco_the_kinematic_estimate_stands(client, monkeypatch):
    monkeypatch.setattr(arm_simulation, "mujoco", None)
    reader, heater, arm, _, _ = placed_cell(client)
    checked = preview(client, placements(reader, heater, arm))
    assert checked["simulation"] is None
    [motion] = checked["motions"]
    assert "simulation" not in motion and motion["seconds"] > 0


HOME = [math.radians(v) for v in (60, -90, 90, -90, -90, 0)]


def path(turn, n=200, dt=0.04):
    """The base joint turning smoothly from the UR home pose, already timed."""
    ease = [10 * u**3 - 15 * u**4 + 6 * u**5 for u in (k / n for k in range(n + 1))]
    return {
        "dt": dt,
        "joints": [[HOME[0] + turn * e, *HOME[1:]] for e in ease],
        "boxes": [
            {"name": "Table", "min": [-1, -1, -0.1], "max": [1, 1, -0.01], "stand": True},
        ],
        "tool_m": 0.204,
    }


def post(client, body):
    return client.post("/api/workcell/arm-path/simulate", json=body)


def test_a_hand_designed_path_runs_in_the_simulation(client):
    response = post(client, path(1.2))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["problem"] is None and result["engine"] == "mujoco"
    # The author's timing is kept: 200 samples of 40 ms, plus settling.
    assert 8.0 <= result["seconds"] <= 8.5
    assert result["torque_ratio"] < 1 and result["tracking_deg"] < 1


def test_a_keep_out_in_the_way_is_named_with_its_time(client):
    body = path(1.2)
    # A post standing where the forearm ends up.
    identity = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    x, y, z = arm_simulation.Bench(ARMS["ur5e"], identity, 0.204, []).flange(body["joints"][-1])
    post_box = {
        "name": "OT-2 frame",
        "min": [x - 0.05, y - 0.05, 0],
        "max": [x + 0.05, y + 0.05, z],
    }
    body["boxes"].append(post_box)
    result = post(client, body).json()
    assert "hits OT-2 frame at" in result["problem"]
    assert 0 < result["collision"]["at_s"] < 8


def test_arm_path_requests_are_bounded_and_need_identity(app, client):
    assert post(client, {**path(1.2), "dt": 0.5}).status_code == 422
    assert post(client, {**path(1.2), "joints": [HOME]}).status_code == 422
    assert post(client, path(1.2, n=5000, dt=0.1)).status_code == 422
    inverted = {"name": "Bad", "min": [0, 0, 0], "max": [0, 1, 1]}
    assert post(client, {**path(1.2), "boxes": [inverted]}).status_code == 422
    from fastapi.testclient import TestClient

    assert post(TestClient(app), path(1.2)).status_code == 401
