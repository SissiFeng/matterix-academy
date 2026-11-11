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

from .arms import ARMS
from .mock_contract import PlanError

# The physics needs no renderer; without this the import looks for a display library.
os.environ.setdefault("MUJOCO_GL", "disable")
try:
    import mujoco
    import numpy as np
except ImportError:  # the kinematic estimate stands in where MuJoCo is not installed
    mujoco = None

ENGINE = "mujoco"
TIMESTEP = 0.002
PAYLOAD_KG = 1.1  # a two-finger gripper holding a filled plate
TOOL_RADIUS = 0.045
MARGIN = 0.25  # clearances are measured up to this distance
CHECK_RAD = 0.02  # joint travel between clearance checks, about a centimetre at the wrist
SAFETY = 0.01  # the planner's required clearance
SPEED_RESERVE = 0.8  # share of the speed cap the connector uses, the rest is for pausing
SETTLE_DEG = 0.2
SETTLE_SECONDS = 2.0
KP, KV = 400.0, 40.0  # computed-torque gains: critically damped at 20 rad/s
TRACKING_LIMIT_DEG = 2.0

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


def scene_xml(twins, layout, actor, arm, base, tool):
    """The whole bench: every placed instrument as static boxes, the bench and the arm."""
    boxes = []
    for placement in layout["placements"]:
        twin = twins[placement["twin_id"]]
        yaw = math.radians(placement["yaw"])
        c, s = math.cos(yaw), math.sin(yaw)
        for n, part in enumerate(twin["spec"]["parts"]):
            px, py, pz = part["position"]
            # The planner's yaw: local (x, z) -> (c x + s z, -s x + c z), about world y.
            x, z = placement["x"] + c * px + s * pz, placement["z"] - s * px + c * pz
            half = [v / 2 for v in part["size"]]
            boxes.append(
                f'<geom name="box:{twin["id"]}:{n}" class="fixed" type="box" '
                f'size="{_fmt(half)}" pos="{_fmt((x, py, z))}" '
                f'quat="{_fmt((math.cos(yaw / 2), 0, math.sin(yaw / 2), 0))}"/>'
            )
    torque = BODIES[arm.key]["torque"]
    motors = "\n".join(
        f'<motor name="m{i}" joint="j{i}" ctrlrange="{-torque[i]} {torque[i]}"/>' for i in range(6)
    )
    return f"""<mujoco model="bench">
  <compiler angle="radian" autolimits="true"/>
  <option timestep="{TIMESTEP}" gravity="0 -9.81 0" integrator="implicitfast"/>
  <default>
    <default class="arm">
      <geom contype="0" conaffinity="0" mass="0"/>
    </default>
    <default class="fixed">
      <geom contype="0" conaffinity="0"/>
    </default>
  </default>
  <worldbody>
    <geom name="bench" class="fixed" type="box" size="5 0.05 5" pos="0 -0.05 0"/>
    {"".join(boxes)}
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
    """One compiled bench, reused for every transfer the same arm makes on it."""

    def __init__(self, twins, layout, actor, arm, base, tool):
        self.arm, self.actor_id = arm, actor["id"]
        self.model = mujoco.MjModel.from_xml_string(
            scene_xml(twins, layout, actor, arm, base, tool)
        )
        self.data = mujoco.MjData(self.model)
        self.names = [
            mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_GEOM, i)
            for i in range(self.model.ngeom)
        ]
        self.labels = {t["id"]: t["spec"]["name"] for t in twins.values()}
        self.torque = np.array(BODIES[arm.key]["torque"], dtype=float)
        self.rated = [math.radians(v) for v in BODIES[arm.key]["speed"]]
        self.pairs = self._pairs()

    def flange(self, q):
        """World position of the flange at a joint vector, for checking the mounting."""
        self.data.qpos[:] = q
        mujoco.mj_kinematics(self.model, self.data)
        return self.data.site("flange").xpos.copy()

    def _pairs(self):
        """Every (arm geom, other geom, link, obstacle, twin id) whose distance matters."""
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
                elif link in ("shoulder", "upper arm") and (
                    name == "bench" or name.split(":")[1] == self.actor_id
                ):
                    continue  # the base stands on its own pedestal
                elif name == "bench":
                    pairs.append((i, j, link, "the bench", ""))
                else:
                    twin_id = name.split(":")[1]
                    pairs.append((i, j, link, self.labels[twin_id], twin_id))
        return pairs

    def _measure(self, out, label, touching):
        model, data = self.model, self.data
        for i, j, link, obstacle, twin_id in self.pairs:
            if twin_id in touching and link in ("gripper", "wrist 3"):
                continue  # the gripper reaches into the station it serves
            key = "self_clearance_m" if twin_id is None else "clearance_m"
            if model.geom_rbound[i] + model.geom_rbound[j] + out[key] < np.linalg.norm(
                data.geom_xpos[i] - data.geom_xpos[j]
            ):
                continue
            gap = mujoco.mj_geomDistance(model, data, i, j, out[key], None)
            if gap < out[key]:
                out[key] = float(gap)
                if twin_id is not None:
                    out["nearest"] = obstacle
                if gap < (0.0 if twin_id is None else SAFETY) and not out["collision"]:
                    out["collision"] = {"segment": label, "link": link, "blocked_by": obstacle}

    def run(self, segments, speed, dwell):
        """Track every segment in turn; segments are (label, joints, station ids)."""
        model, data = self.model, self.data
        mujoco.mj_resetData(model, data)
        data.qpos[:] = segments[0][1][0]
        mujoco.mj_forward(model, data)
        out = {
            "seconds": 0.0,
            "tracking_deg": 0.0,
            "torque_ratio": 0.0,
            "clearance_m": MARGIN,
            "self_clearance_m": MARGIN,
            "nearest": None,
            "collision": None,
        }
        inertial = np.zeros(model.nv)
        for label, joints, touching in segments:
            duration, at = _profile(joints, speed, self.rated)
            steps = math.ceil(duration / TIMESTEP)
            settle = math.ceil(SETTLE_SECONDS / TIMESTEP)
            previous = np.array(at(0.0))
            checked = data.qpos.copy()
            self._measure(out, label, touching)
            for n in range(1, steps + settle + 1):
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
                    self._measure(out, label, touching)
                lag = float(np.max(np.abs(target - data.qpos)))
                if n <= steps:
                    out["tracking_deg"] = max(out["tracking_deg"], math.degrees(lag))
                elif lag < math.radians(SETTLE_DEG) and float(
                    np.max(np.abs(data.qvel))
                ) < math.radians(SETTLE_DEG):
                    break
            out["seconds"] += n * TIMESTEP
        out["seconds"] = round(out["seconds"] + dwell, 1)
        for key in ("tracking_deg", "torque_ratio"):
            out[key] = round(out[key], 2)
        for key in ("clearance_m", "self_clearance_m"):
            out[key] = round(out[key], 3)
        return out


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
    return {
        "engine": ENGINE,
        "version": mujoco.__version__,
        "speed": speed,
        "payload_kg": PAYLOAD_KG,
        **result,
    }


assert set(BODIES) == set(ARMS)
