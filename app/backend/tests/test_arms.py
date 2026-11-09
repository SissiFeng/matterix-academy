import math
from copy import deepcopy

import pytest

from academy import workcell_layout as wl
from academy.arms import ARMS, ELBOW_MIN_DEG, arm_for
from academy.mock_contract import PlanError
from academy.simple_twins import TEMPLATES, TwinSpec


def cell(arm=None, distance=0.6, limits=()):
    arm_spec = deepcopy(TEMPLATES["transfer-arm"])
    if arm:
        arm_spec["arm"] = arm
    if limits:
        arm_spec["joint_limits_deg"] = list(limits)
    twins = {
        "arm": {"id": "arm", "spec": arm_spec, "confirmed": True, "mode": "mock"},
        "a": {"id": "a", "spec": TEMPLATES["heater"], "confirmed": True, "mode": "mock"},
        "b": {"id": "b", "spec": TEMPLATES["reader"], "confirmed": True, "mode": "mock"},
    }
    layout = {
        "bench": {"width": 4.0, "depth": 3.0},
        "placements": [
            {"twin_id": "arm", "x": 0.0, "z": 0.0, "yaw": 0, "access": "top"},
            {"twin_id": "a", "x": -distance, "z": 0.0, "yaw": 0, "access": "top"},
            {"twin_id": "b", "x": distance, "z": 0.0, "yaw": 0, "access": "top"},
        ],
    }
    steps = [
        {"device_id": "a", "operation": "load", "value": 100},
        {
            "device_id": "arm",
            "operation": "transfer",
            "source_id": "a",
            "target_id": "b",
            "value": 1,
        },
    ]
    return twins, layout, steps


def test_profiles_are_ordered_by_reach_and_narrowed_by_the_connector():
    assert ARMS["ur3e"].reach < ARMS["ur5e"].reach < ARMS["ur10e"].reach
    narrowed = arm_for({"arm": "ur10e", "joint_limits_deg": [300, 300, 120, 300, 300, 300]})
    assert narrowed.name == "UR10e"
    assert math.degrees(narrowed.limits[2]) == pytest.approx(120)
    # A connector can only narrow the profile, never widen it.
    wider = arm_for({"joint_limits_deg": [360] * 6})
    assert wider.limits == ARMS["ur5e"].limits


def test_spec_rejects_an_arm_on_a_station():
    with pytest.raises(ValueError, match="carries an arm"):
        TwinSpec.model_validate({**TEMPLATES["reader"], "arm": "ur10e"})
    with pytest.raises(ValueError, match="six joint limits"):
        TwinSpec.model_validate({**TEMPLATES["transfer-arm"], "joint_limits_deg": [90]})


def test_a_longer_arm_reaches_stations_a_ur5e_cannot():
    twins, layout, steps = cell(distance=1.05)
    with pytest.raises(PlanError):
        wl.plan_workflow(twins, layout, steps)
    twins, layout, steps = cell("ur10e", distance=1.05)
    [motion] = wl.plan_workflow(twins, layout, steps)
    assert motion["arm"] == "UR10e"
    assert motion["elbow_deg"] >= ELBOW_MIN_DEG


def test_paths_keep_the_elbow_bent():
    twins, layout, steps = cell()
    [motion] = wl.plan_workflow(twins, layout, steps)
    assert motion["elbow_deg"] >= ELBOW_MIN_DEG


def test_export_is_for_the_ur5e_connector_only():
    twins, layout, steps = cell("ur10e")
    with pytest.raises(PlanError, match="UR5e connector only"):
        wl.action_chain(twins, layout, steps, 2, 20)
