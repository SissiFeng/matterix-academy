"""Rigid-body simulation of a planned transfer in MuJoCo.

The bench planner finds a path with line-model kinematics and a constant-speed time
estimate. This module replays that path in a MuJoCo model of the same bench: the arm
has Universal Robots' link offsets, masses and joint torque limits, a controller tracks
the path under gravity with a carried payload, and MuJoCo reports how long the move
takes, how closely it is tracked, how much joint torque it needs and how close the arm
comes to the instruments and to itself.

Arm structure, collision envelopes and UR5e/UR10e inertias follow the MuJoCo Menagerie
models (Apache-2.0); UR3e masses and all torque and speed limits are Universal Robots'
published values. Kinematic lengths are the same DH parameters the planner uses, so a
joint vector means the same pose in both. Instruments are the boxes of their twin specs.

A simulated result is not a measurement: instrument dimensions and device durations
are whatever the twin states, and no physical robot has run the path.
"""

import itertools
import math
import os
import time

from .arms import ARMS
from .collision import shapes
from .mock_contract import PlanError

# The physics needs no renderer; without this the import looks for a display library.
os.environ.setdefault("MUJOCO_GL", "disable")
try:
    import mujoco
    import numpy as np
except ImportError:  # the kinematic estimate stands in where MuJoCo is not installed
    mujoco = None

ENGINE = "mujoco"
TIMESTEP = 0.004  # well inside the controller's 20 rad/s bandwidth
PAYLOAD_KG = 1.1  # a two-finger gripper holding a filled plate
TOOL_RADIUS = 0.045
MARGIN = 0.25  # clearances are measured up to this distance
# Joint travel between clearance checks. A link tip then moves about a centimetre, under
# the thinnest link's radius, so no link can pass through an instrument between checks.
CHECK_RAD = 0.01
SAFETY = 0.01  # the planner's required clearance
SPEED_RESERVE = 0.8  # share of the speed cap the connector uses, the rest is for pausing
SETTLE_DEG = 0.2
SETTLE_SECONDS = 2.0
KP, KV = 400.0, 40.0  # computed-torque gains: critically damped at 20 rad/s
TRACKING_LIMIT_DEG = 2.0
PLAY_SECONDS = 8.0  # computing time one submitted trajectory may take

# so/eo: shoulder and elbow offsets along the joint axes that DH parameters leave out.
BODIES = {
    "ur3e": {
        "so": 0.120,
        "eo": -0.0925,
        "mass": (2.0, 1.98, 3.4445, 1.437, 0.871, 0.805, 0.261),
        "inertia": None,
        "torque": (54, 54, 28, 9, 9, 9),
        "speed": (180, 180, 180, 360, 360, 360),
        "radii": (0.045, 0.04, 0.04, 0.032, 0.032),
    },
    "ur5e": {
        "so": 0.138,
        "eo": -0.131,
        "mass": (4.0, 3.7, 8.393, 2.275, 1.219, 1.219, 0.1889),
        "inertia": (
            (0.00443333156, 0.00443333156, 0.0072),
            (0.0102675, 0.0102675, 0.00666),
            (0.133886, 0.133886, 0.0151074),
            (0.0311796, 0.0311796, 0.004095),
            (0.0025599, 0.0025599, 0.0021942),
            (0.0025599, 0.0025599, 0.0021942),
            (0.000132134, 9.90863e-05, 9.90863e-05),
        ),
        "torque": (150, 150, 150, 28, 28, 28),
        "speed": (180, 180, 180, 180, 180, 180),
        "radii": (0.06, 0.05, 0.055, 0.038, 0.04),
    },
    "ur10e": {
        "so": 0.176,
        "eo": -0.137,
        "mass": (4.0, 7.778, 12.93, 3.87, 1.96, 1.96, 0.202),
        "inertia": (
            (0.0061063308908, 0.0061063308908, 0.01125),
            (0.0314743, 0.0314743, 0.0218756),
            (0.423074, 0.423074, 0.0363656),
            (0.11059, 0.11059, 0.0108844),
            (0.0055125, 0.00510825, 0.00510825),
            (0.0055125, 0.00510825, 0.00510825),
            (0.000204525, 0.000144346, 0.000144346),
        ),
        "torque": (330, 330, 150, 56, 56, 56),
        "speed": (120, 120, 180, 180, 180, 180),
        "radii": (0.078, 0.06, 0.058, 0.043, 0.048),
    },
}


def available():
    return mujoco is not None


def _rod(mass, radius, length):
    """Principal inertias of a solid cylinder lying along z."""
    across = mass * (3 * radius**2 + length**2) / 12
    return across, across, mass * radius**2 / 2


def _fmt(values):
    return " ".join(f"{v:.6g}" for v in values)


def _quat(rows):
    """Unit quaternion (w, x, y, z) of a rotation given as three rows."""
    out = np.zeros(4)
    mujoco.mju_mat2Quat(out, np.array(rows, dtype=float).reshape(9))
    return out


def arm_xml(arm, base, tool):
    """The arm as MJCF bodies, mounted at the planner's base frame (a 4x4, y up)."""
    body = BODIES[arm.key]
    d, a = arm.d, arm.a
    upper, fore = -a[1], -a[2]
    wrist = d[3] - body["so"] - body["eo"]
    r_sh, r_up, r_el, r_fo, r_wr = body["radii"]
    k = r_sh / 0.06  # joint housings scale with the shoulder joint
    lengths = (0.1, 0.12, upper, fore, 0.12, 0.12, 0.05)
    radii = (r_sh, r_sh, r_up, r_fo, r_wr, r_wr, r_wr)
    inertia = body["inertia"] or tuple(
        _rod(m, r, n) for m, r, n in zip(body["mass"], radii, lengths, strict=True)
    )
    centres = (
        (0, 0, 0),
        (0, 0, 0),
        (0, 0, upper / 2),
        (0, 0, fore / 2),
        (0, wrist, 0),
        (0, 0, d[4]),
        (0, 0.77 * d[5], 0),
    )

    def inertial(i):
        return (
            f'<inertial mass="{body["mass"][i]}" pos="{_fmt(centres[i])}" '
            f'diaginertia="{_fmt(inertia[i])}"/>'
        )

    def joint(i, axis="0 1 0"):
        lo, hi = -arm.limits[i], arm.limits[i]
        return (
            f'<joint name="j{i}" axis="{axis}" range="{lo:.5f} {hi:.5f}" armature="0.1" '
            f'damping="1"/>'
        )

    serial = itertools.count()

    def capsule(link, radius, half, pos, across=False, kind="capsule"):
        turn = ' quat="1 1 0 0"' if across else ""
        return (
            f'<geom name="arm:{link}:{next(serial)}" class="arm" type="{kind}" '
            f'size="{radius:.4f} {half:.4f}" pos="{_fmt(pos)}"{turn}/>'
        )

    rotation = [row[:3] for row in base[:3]]
    # Menagerie's base is turned half a turn about its axis, as in the UR URDF.
    half_turn = [[-1, 0, 0], [0, -1, 0], [0, 0, 1]]
    mounted = [
        [sum(rotation[i][n] * half_turn[n][j] for n in range(3)) for j in range(3)]
        for i in range(3)
    ]
    position = [row[3] for row in base[:3]]
    return f"""
    <body name="arm" pos="{_fmt(position)}" quat="{_fmt(_quat(mounted))}">
      {inertial(0)}
      <body pos="0 0 {d[0]}">
        {inertial(1)}
        {joint(0, "0 0 1")}
        {capsule("shoulder", r_sh, 0.06 * k, (0, 0, -0.04 * k))}
        <body pos="0 {body["so"]} 0" quat="1 0 1 0">
          {inertial(2)}
          {joint(1)}
          {capsule("upper arm", r_sh, 0.06 * k, (0, -0.04 * k, 0), across=True)}
          {capsule("upper arm", r_up, 0.47 * upper, (0, 0, 0.48 * upper))}
          <body pos="0 {body["eo"]} {upper}">
            {inertial(3)}
            {joint(2)}
            {capsule("forearm", r_el, 0.06 * k, (0, 0.08 * k, 0), across=True)}
            {capsule("forearm", r_fo, 0.48 * fore, (0, 0, 0.5 * fore))}
            <body pos="0 0 {fore}" quat="1 0 1 0">
              {inertial(4)}
              {joint(3)}
              {capsule("wrist 1", r_wr, 0.07 * k, (0, 0.05 * k, 0), across=True)}
              <body pos="0 {wrist} 0">
                {inertial(5)}
                {joint(4, "0 0 1")}
                {capsule("wrist 2", r_wr, 0.06 * k, (0, 0, 0.04 * k))}
                {capsule("wrist 2", r_wr, 0.04 * k, (0, 0.02 * k, d[4]), across=True)}
                <body pos="0 0 {d[4]}">
                  {inertial(6)}
                  {joint(5)}
                  {capsule("wrist 3", r_wr, 0.02, (0, d[5] - 0.02, 0), True, "cylinder")}
                  <site name="flange" pos="0 {d[5]} 0" quat="-1 1 0 0"/>
                  <body>
                    <geom name="arm:gripper:0" class="arm" type="capsule" size="{TOOL_RADIUS}"
                      fromto="0 {d[5] + TOOL_RADIUS} 0 0 {d[5] + tool - TOOL_RADIUS} 0"
                      mass="{PAYLOAD_KG}"/>
                  </body>
                </body>
              </body>
            </body>
          </body>
        </body>
      </body>
    </body>"""


def layout_boxes(twins, layout, actor):
    """Every placed instrument as static boxes, in the planner's y-up frame."""
    boxes = []
    for placement in layout["placements"]:
        twin = twins[placement["twin_id"]]
        yaw = math.radians(placement["yaw"])
        c, s = math.cos(yaw), math.sin(yaw)
        for (px, py, pz), half in shapes(twin):
            # The planner's yaw: local (x, z) -> (c x + s z, -s x + c z), about world y.
            x, z = placement["x"] + c * px + s * pz, placement["z"] - s * px + c * pz
            boxes.append(
                {
                    "id": twin["id"],
                    "name": twin["spec"]["name"],
                    "half": list(half),
                    "pos": (x, py, z),
                    "quat": (math.cos(yaw / 2), 0, math.sin(yaw / 2), 0),
                    # The base stands on its own base plate.
                    "stand": twin["id"] == actor["id"],
                }
            )
    # The bench top, which the arm's base plate rests on.
    boxes.append(
        {
            "id": "",
            "name": "the bench",
            "half": (5, 0.05, 5),
            "pos": (0, -0.05, 0),
            "quat": (1, 0, 0, 0),
            "stand": True,
        }
    )
    return boxes


def scene_xml(arm, base, tool, boxes, gravity):
    """Static boxes and the arm. A box marked `stand` may touch the arm's base links."""
    geoms = "".join(
        f'<geom name="box:{n}" class="fixed" type="box" size="{_fmt(box["half"])}" '
        f'pos="{_fmt(box["pos"])}" quat="{_fmt(box["quat"])}"/>'
        for n, box in enumerate(boxes)
    )
    torque = BODIES[arm.key]["torque"]
    motors = "\n".join(
        f'<motor name="m{i}" joint="j{i}" ctrlrange="{-torque[i]} {torque[i]}"/>' for i in range(6)
    )
    return f"""<mujoco model="bench">
  <compiler angle="radian" autolimits="true"/>
  <option timestep="{TIMESTEP}" gravity="{_fmt(gravity)}" integrator="implicitfast"/>
  <default>
    <default class="arm">
      <geom contype="0" conaffinity="0" mass="0"/>
    </default>
    <default class="fixed">
      <geom contype="0" conaffinity="0"/>
    </default>
  </default>
  <worldbody>
    {geoms}
    {arm_xml(arm, base, tool)}
  </worldbody>
  <actuator>
    {motors}
  </actuator>
</mujoco>"""


def _span(a, b):
    return max(abs(x - y) for x, y in zip(a, b, strict=True))


def _profile(joints, speed, limits):
    """Rest-to-rest timing along a dense joint path: (duration, position at time t).

    The largest joint change advances at the speed cap, with the acceleration the UR
    connector allows itself, and no joint may exceed its own rated speed.
    """
    marks = [0.0]
    for a, b in zip(joints, joints[1:], strict=False):
        marks.append(marks[-1] + _span(a, b))
    total = marks[-1]
    rated = min(limits)
    v = min(math.radians(speed) * SPEED_RESERVE, rated)
    accel = 2 * v
    ramp = v / accel
    if total < v * ramp:
        ramp = math.sqrt(total / accel)
        v = accel * ramp
    duration = 2 * ramp + (total - v * ramp) / v if total else 0.0

    def at(t):
        if t <= 0 or not total:
            return joints[0]
        if t >= duration:
            return joints[-1]
        if t < ramp:
            s = accel * t * t / 2
        elif t > duration - ramp:
            s = total - accel * (duration - t) ** 2 / 2
        else:
            s = v * (t - ramp / 2)
        lo, hi = 0, len(marks) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            lo, hi = (mid, hi) if marks[mid] <= s else (lo, mid)
        f = (s - marks[lo]) / (marks[hi] - marks[lo]) if marks[hi] > marks[lo] else 0.0
        return [x + f * (y - x) for x, y in zip(joints[lo], joints[hi], strict=True)]

    return duration, at


class Bench:
    """One compiled scene, reused for every move the same arm makes in it."""

    def __init__(self, arm, base, tool, boxes, gravity=(0, -9.81, 0)):
        self.arm, self.boxes = arm, boxes
        self.model = mujoco.MjModel.from_xml_string(scene_xml(arm, base, tool, boxes, gravity))
        self.data = mujoco.MjData(self.model)
        self.names = [
            mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_GEOM, i)
            for i in range(self.model.ngeom)
        ]
        self.torque = np.array(BODIES[arm.key]["torque"], dtype=float)
        self.rated = [math.radians(v) for v in BODIES[arm.key]["speed"]]
        self.pairs = self._pairs()

    @classmethod
    def of_layout(cls, twins, layout, actor, arm, base, tool):
        return cls(arm, base, tool, layout_boxes(twins, layout, actor))

    def flange(self, q):
        """World position of the flange at a joint vector, for checking the mounting."""
        self.data.qpos[:] = q
        mujoco.mj_kinematics(self.model, self.data)
        return self.data.site("flange").xpos.copy()

    def _pairs(self):
        """Every (arm geom, other geom, link, obstacle, box id) whose distance matters."""
        model, pairs = self.model, []
        arm = [i for i, name in enumerate(self.names) if name.startswith("arm:")]
        # The carried tool is one rigid piece with the last link.
        welded = model.body_weldid[model.geom_bodyid]
        for i in arm:
            link = self.names[i].split(":")[1]
            for j, name in enumerate(self.names):
                if name.startswith("arm:"):
                    # Neighbouring links share a joint housing and always touch.
                    if j > i and welded[j] - welded[i] > 1:
                        pairs.append((i, j, link, f"its own {name.split(':')[1]}", None))
                    continue
                box = self.boxes[int(name.split(":")[1])]
                if not (box["stand"] and link in ("shoulder", "upper arm")):
                    pairs.append((i, j, link, box["name"], box["id"]))
        return pairs

    def _measure(self, out, label, touching, now):
        model, data = self.model, self.data
        for i, j, link, obstacle, box_id in self.pairs:
            if link == "gripper" and (touching is None or box_id in touching):
                continue  # the gripper reaches into the station it serves
            key = "self_clearance_m" if box_id is None else "clearance_m"
            if model.geom_rbound[i] + model.geom_rbound[j] + out[key] < np.linalg.norm(
                data.geom_xpos[i] - data.geom_xpos[j]
            ):
                continue
            gap = mujoco.mj_geomDistance(model, data, i, j, out[key], None)
            if gap < out[key]:
                out[key] = float(gap)
                if box_id is not None:
                    out["nearest"] = obstacle
                if gap < (0.0 if box_id is None else SAFETY) and not out["collision"]:
                    out["collision"] = {
                        "segment": label,
                        "link": link,
                        "blocked_by": obstacle,
                        "at_s": round(now, 2),
                    }

    def _follow(self, out, label, at, duration, touching, deadline=math.inf):
        """Track `at(t)` for `duration`, then let the arm settle; adds to `out`."""
        model, data = self.model, self.data
        inertial = np.zeros(model.nv)
        steps = math.ceil(duration / TIMESTEP)
        settle = math.ceil(SETTLE_SECONDS / TIMESTEP)
        previous = np.array(at(0.0))
        checked = data.qpos.copy()
        began = out["seconds"]
        self._measure(out, label, touching, began)
        n = 0
        for n in range(1, steps + settle + 1):
            if not n % 256 and time.monotonic() > deadline:
                raise PlanError("constraint", "This path takes too long to simulate here")
            target = np.array(at(n * TIMESTEP))
            error = target - data.qpos
            rate = (target - previous) / TIMESTEP - data.qvel
            previous = target
            mujoco.mj_mulM(model, data, inertial, KP * error + KV * rate)
            wanted = data.qfrc_bias + inertial
            out["torque_ratio"] = max(
                out["torque_ratio"], float(np.max(np.abs(wanted) / self.torque))
            )
            data.ctrl[:] = np.clip(wanted, -self.torque, self.torque)
            mujoco.mj_step(model, data)
            if float(np.max(np.abs(data.qpos - checked))) > CHECK_RAD or n == steps:
                checked = data.qpos.copy()
                self._measure(out, label, touching, began + n * TIMESTEP)
            lag = float(np.max(np.abs(target - data.qpos)))
            out["tracking_deg"] = max(out["tracking_deg"], math.degrees(lag))
            if (
                n > steps
                and lag < math.radians(SETTLE_DEG)
                and float(np.max(np.abs(data.qvel))) < math.radians(SETTLE_DEG)
            ):
                break
        out["seconds"] += n * TIMESTEP

    def _begin(self, start):
        mujoco.mj_resetData(self.model, self.data)
        self.data.qpos[:] = start
        mujoco.mj_forward(self.model, self.data)
        return {
            "seconds": 0.0,
            "tracking_deg": 0.0,
            "torque_ratio": 0.0,
            "clearance_m": MARGIN,
            "self_clearance_m": MARGIN,
            "nearest": None,
            "collision": None,
        }

    @staticmethod
    def _rounded(out, extra=0.0):
        out["seconds"] = round(out["seconds"] + extra, 1)
        for key in ("tracking_deg", "torque_ratio"):
            out[key] = round(out[key], 2)
        for key in ("clearance_m", "self_clearance_m"):
            out[key] = round(out[key], 3)
        return out

    def run(self, segments, speed, dwell):
        """Track every segment in turn; segments are (label, joints, station ids)."""
        out = self._begin(segments[0][1][0])
        for label, joints, touching in segments:
            duration, at = _profile(joints, speed, self.rated)
            self._follow(out, label, at, duration, touching)
        return self._rounded(out, dwell)

    def play(self, joints, dt):
        """Track a trajectory already timed by its author: one joint vector every `dt`.

        The gripper is left to the author's own tool checks; links are checked here.
        """
        out = self._begin(joints[0])
        last = len(joints) - 1

        def at(t):
            k = min(int(t / dt), last - 1)
            f = min(1.0, t / dt - k)
            return [a + f * (b - a) for a, b in zip(joints[k], joints[k + 1], strict=True)]

        self._follow(out, "trajectory", at, last * dt, None, time.monotonic() + PLAY_SECONDS)
        return self._rounded(out)


def describe(speed):
    """What a simulated result was run with, or None where MuJoCo is not installed."""
    if not available():
        return None
    return {
        "engine": ENGINE,
        "version": mujoco.__version__,
        "speed": speed,
        "payload_kg": PAYLOAD_KG,
    }


def simulate(bench, step_no, segments, speed, dwell):
    """The simulated result of one transfer, or PlanError when the arm cannot do it."""
    result = bench.run(segments, speed, dwell)
    hit = result.pop("collision")
    # An overloaded arm sags into whatever is below it, so the load is named first.
    if result["torque_ratio"] > 1:
        raise PlanError(
            "geometry",
            f"Step {step_no}: the {bench.arm.name} needs {result['torque_ratio']:.1f}× its "
            "rated joint torque to carry the load along this path",
        )
    if hit:
        error = PlanError(
            "geometry",
            f"Step {step_no}: in simulation the {hit['link']} hits {hit['blocked_by']} "
            f"({hit['segment'].lower()})",
        )
        error.hit = hit
        raise error
    if result["tracking_deg"] > TRACKING_LIMIT_DEG:
        raise PlanError(
            "geometry",
            f"Step {step_no}: the {bench.arm.name} strays {result['tracking_deg']:.1f}° from "
            "this path in simulation",
        )
    return {**describe(speed), **result}


def play(arm_key, joints, dt, boxes, tool):
    """Run a hand-designed joint trajectory in the arm's own base frame (z up).

    `boxes` are axis-aligned keep-outs {name, min, max, stand}. The verdict is returned
    rather than raised, so the designer sees what the simulation found either way.
    """
    arm = ARMS[arm_key]
    scene = [
        {
            "id": n,
            "name": box["name"],
            "half": [(hi - lo) / 2 for lo, hi in zip(box["min"], box["max"], strict=True)],
            "pos": [(hi + lo) / 2 for lo, hi in zip(box["min"], box["max"], strict=True)],
            "quat": (1, 0, 0, 0),
            "stand": box["stand"],
        }
        for n, box in enumerate(boxes)
    ]
    base = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    result = Bench(arm, base, tool, scene, gravity=(0, 0, -9.81)).play(joints, dt)
    hit = result["collision"]
    if result["torque_ratio"] > 1:
        problem = f"The {arm.name} needs {result['torque_ratio']:.1f}× its rated joint torque"
    elif hit:
        problem = f"The {hit['link']} hits {hit['blocked_by']} at {hit['at_s']:.1f} s"
    elif result["tracking_deg"] > TRACKING_LIMIT_DEG:
        problem = f"The {arm.name} strays {result['tracking_deg']:.1f}° from the path"
    else:
        problem = None
    return {
        "engine": ENGINE,
        "version": mujoco.__version__,
        "payload_kg": PAYLOAD_KG,
        **result,
        "problem": problem,
    }


assert set(BODIES) == set(ARMS)
