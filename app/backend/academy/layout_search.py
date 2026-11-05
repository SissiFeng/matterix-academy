"""Feasible bench layouts for a saved workflow.

Places every transfer arm, then every station it serves on rings around it, facing the
arm, and keeps a layout only when `plan_workflow` finds every transfer. The goal is a
feasible layout, not an optimal one: the total tool path only orders what was found.
Each attempt is seeded, so the same inputs give the same layouts while the search stays
under its time cap.

Synthetic geometry only, exactly as checked by the planner it calls.
"""

import math
import random
import time

from .mock_contract import PlanError
from .workcell_layout import (
    APPROACH,
    ARM,
    GRIPPER,
    REACH,
    TOOL,
    D,
    Planner,
    _add,
    _col,
    _norm,
    _overlap,
    _sub,
    _yaw,
    access,
    corners,
    footprint,
    mount,
    plan_workflow,
    validate_layout,
)

RADII = (0.42, 0.55, 0.68)  # arm base to access point, on the bench plane
ANGLES = tuple(range(0, 360, 30))
SIDES = ("top", "front")
ARM_GRID = 0.2
SPARE_GRID = 0.1
MARGIN = 0.02  # reach kept in reserve so a pose is not at full stretch
FULL_PLANS = 24
ATTEMPT_PLANS = 8
SECONDS = 8.0
DISTINCT = 0.25  # metres one instrument must move for a layout to count as new


def _base(twins, placement):
    frame = mount(twins[placement["twin_id"]]["spec"], placement)
    return frame[0][3], frame[2][3]


def _pose(spec, side, point, toward):
    """The placement whose access point is at `point` with its front facing `toward`."""
    yaw = round(math.degrees(math.atan2(toward[0] - point[0], toward[1] - point[1])))
    yaw = 180 if yaw == -180 else yaw
    x0, x1, z0, z1 = footprint(spec)
    local = ((x0 + x1) / 2, z1 + 0.04 if side == "front" else (z0 + z1) / 2)
    rx, rz = _yaw(yaw, *local)
    # Adding 0.0 turns a rounded -0.0 into 0.0.
    x, z = round(point[0] - rx, 2) + 0.0, round(point[1] - rz, 2) + 0.0
    return {"x": x, "z": z, "yaw": yaw, "access": side}


class Search:
    def __init__(self, twins, bench, steps, fixed, seconds):
        self.twins, self.bench, self.steps = twins, bench, steps
        self.deadline = time.monotonic() + seconds
        self.fixed = {p["twin_id"]: p for p in fixed}
        transfers = [s for s in steps if s["operation"] == "transfer"]
        if not transfers:
            raise PlanError("state", "Save a workflow with a transfer step to search for a layout")
        self.arms = list(dict.fromkeys(s["device_id"] for s in transfers))
        self.serving, uses = {}, {}
        for s in transfers:
            for key in ("source_id", "target_id"):
                arms = self.serving.setdefault(s[key], [])
                if s["device_id"] not in arms:
                    arms.append(s["device_id"])
                uses[s[key]] = uses.get(s[key], 0) + 1
        # Busiest stations first: they constrain the layout most.
        self.stations = sorted(
            (t for t in self.serving if t not in self.fixed), key=lambda t: -uses[t]
        )
        busy = {*self.arms, *self.serving}
        self.spares = [t for t in twins if t not in busy and t not in self.fixed]
        self.plans = 0
        self.failure = None
        self.reach_cache = {}
        validate_layout(twins, self.layout(self.fixed.values()))

    def layout(self, placements):
        return {
            "bench": self.bench,
            "placements": [{"twin_id": p["twin_id"], **_strip(p)} for p in placements],
        }

    def fits(self, twin_id, placement, placed):
        shape = corners(self.twins[twin_id]["spec"], placement)
        half_w, half_d = self.bench["width"] / 2, self.bench["depth"] / 2
        if any(abs(x) > half_w or abs(z) > half_d for x, z in shape):
            return False
        return not any(
            _overlap(shape, corners(self.twins[p["twin_id"]]["spec"], p)) for p in placed
        )

    def reachable(self, arm_id, station_id, side, radius):
        """Whether the arm can reach this station alone at this radius and side.

        The arm's first joint turns almost fully, so one bearing stands for all of them;
        neighbours are left to the full workflow check.
        """
        key = (arm_id, station_id, side, radius)
        if key not in self.reach_cache:
            arm = {"twin_id": arm_id, "x": 0.0, "z": 0.0, "yaw": 0, "access": "top"}
            bx, bz = _base(self.twins, arm)
            spec = self.twins[station_id]["spec"]
            station = {"twin_id": station_id, **_pose(spec, side, (bx, bz + radius), (bx, bz))}
            layout = self.layout([arm, station])
            point, direction, rotation = access(spec, station)
            flange = _add(_add(point, direction, APPROACH), rotation[2], -TOOL)
            base = mount(self.twins[arm_id]["spec"], arm)
            shoulder = _add(_col(base, 3), _col(base, 2), D[0])
            ok = _norm(_sub(flange, shoulder)) <= REACH - MARGIN
            if ok:
                planner = Planner(self.twins, layout, self.twins[arm_id])
                try:
                    planner.station(self.twins[station_id], {**planner.rest, GRIPPER: {station_id}})
                except PlanError as exc:
                    ok, self.failure = False, str(exc)
            self.reach_cache[key] = ok
        return self.reach_cache[key]

    def arm_poses(self, arm_id, placed, rng):
        half = max(abs(v) for v in footprint(self.twins[arm_id]["spec"]))
        w, d = self.bench["width"] / 2 - half, self.bench["depth"] / 2 - half
        grid = [
            (round(i * ARM_GRID, 2), round(k * ARM_GRID, 2))
            for i in range(-int(w / ARM_GRID), int(w / ARM_GRID) + 1)
            for k in range(-int(d / ARM_GRID), int(d / ARM_GRID) + 1)
        ]
        grid.sort(key=lambda p: (math.hypot(*p), p))
        if rng:
            grid = grid[:3] + rng.sample(grid[3:], len(grid) - 3)
        others = [_base(self.twins, p) for p in placed if p["twin_id"] in self.arms]
        for x, z in grid:
            pose = {"twin_id": arm_id, "x": x, "z": z, "yaw": 0, "access": "top"}
            base = _base(self.twins, pose)
            if any(math.dist(base, o) < 0.6 for o in others):
                continue
            # Fixed stations this arm serves must stay within its reach.
            if any(
                arm_id in self.serving[t]
                and math.dist(base, _access_xz(self.twins, self.fixed[t])) > REACH
                for t in self.fixed
                if t in self.serving
            ):
                continue
            if self.fits(arm_id, pose, placed):
                yield pose

    def station_poses(self, station_id, placed, order):
        spec = self.twins[station_id]["spec"]
        bases = {p["twin_id"]: _base(self.twins, p) for p in placed if p["twin_id"] in self.arms}
        home, *rest = self.serving[station_id]
        bx, bz = bases[home]
        # Next to the stations this arm already serves, for a short swing.
        near = [
            math.degrees(math.atan2(px - bx, pz - bz))
            for px, pz in (
                _access_xz(self.twins, p)
                for p in placed
                if p["twin_id"] in self.serving and home in self.serving[p["twin_id"]]
            )
        ]
        start = near[-1] if near else order["angle"]
        angles = sorted(ANGLES, key=lambda a: (abs((a - start + 180) % 360 - 180), a))
        offered = False
        for side in order["sides"]:
            for radius in order["radii"]:
                if not self.reachable(home, station_id, side, radius):
                    continue
                for angle in angles:
                    t = math.radians(angle)
                    point = (bx + radius * math.sin(t), bz + radius * math.cos(t))
                    if any(math.dist(point, bases[a]) > REACH - MARGIN for a in rest):
                        continue
                    pose = {"twin_id": station_id, **_pose(spec, side, point, (bx, bz))}
                    if self.fits(station_id, pose, placed):
                        offered = True
                        yield pose
        if not offered:
            self.failure = (
                f"{spec['name']} has no pose within the {ARM}'s reach that fits on the bench "
                "beside the instruments already placed"
            )

    def spare_poses(self, twin_id, placed):
        """Instruments outside the workflow go where the arms are least likely to be."""
        bases = [_base(self.twins, p) for p in placed if p["twin_id"] in self.arms]
        w, d = self.bench["width"] / 2, self.bench["depth"] / 2
        grid = [
            (round(i * SPARE_GRID, 2), round(k * SPARE_GRID, 2))
            for i in range(-int(w / SPARE_GRID), int(w / SPARE_GRID) + 1)
            for k in range(-int(d / SPARE_GRID), int(d / SPARE_GRID) + 1)
        ]
        grid.sort(key=lambda p: (-min(math.dist(p, b) for b in bases), p))
        for x, z in grid:
            for yaw in (0, 90):
                pose = {"twin_id": twin_id, "x": x, "z": z, "yaw": yaw, "access": "top"}
                if self.fits(twin_id, pose, placed):
                    return pose
        return None

    def attempt(self, seed, seen):
        rng = random.Random(seed) if seed else None
        order = {
            "angle": rng.choice(ANGLES) if rng else 0,
            "radii": rng.sample(RADII, len(RADII)) if rng else RADII,
            "sides": rng.sample(SIDES, len(SIDES)) if rng else SIDES,
        }
        free_arms = [a for a in self.arms if a not in self.fixed]
        budget = [ATTEMPT_PLANS]

        def place(placed, arms, stations):
            if time.monotonic() > self.deadline or not budget[0] or self.plans >= FULL_PLANS:
                return None
            if arms:
                for pose in self.arm_poses(arms[0], placed, rng):
                    found = place([*placed, pose], arms[1:], stations)
                    if found or not budget[0]:
                        return found
                return None
            if stations:
                for pose in self.station_poses(stations[0], placed, order):
                    found = place([*placed, pose], arms, stations[1:])
                    if found or not budget[0]:
                        return found
                return None
            full = list(placed)
            for twin_id in self.spares:
                pose = self.spare_poses(twin_id, full)
                if pose is None:
                    self.failure = (
                        f"No room left on the bench for {self.twins[twin_id]['spec']['name']}"
                    )
                    return None
                full.append(pose)
            if any(not _distinct(full, other) for other in seen):
                return None
            layout = self.layout(full)
            budget[0] -= 1
            self.plans += 1
            try:
                motions = plan_workflow(self.twins, layout, self.steps)
            except PlanError as exc:
                self.failure = str(exc)
                return None
            seen.append(full)
            return layout, motions

        return place(list(self.fixed.values()), free_arms, self.stations)


def _strip(p):
    return {k: p[k] for k in ("x", "z", "yaw", "access")}


def _access_xz(twins, placement):
    point = access(twins[placement["twin_id"]]["spec"], placement)[0]
    return point[0], point[2]


def _distinct(a, b):
    """Two layouts differ when some instrument stands at least DISTINCT apart."""
    where = {p["twin_id"]: (p["x"], p["z"]) for p in b}
    return any(math.dist((p["x"], p["z"]), where[p["twin_id"]]) >= DISTINCT for p in a)


def suggest_layouts(twins, bench, steps, fixed=(), count=3, seconds=SECONDS):
    """Up to `count` distinct layouts on which every transfer in `steps` has an arm path."""
    search = Search(twins, bench, steps, fixed, seconds)
    found, seen = [], []
    for seed in range(count * 3):
        if len(found) >= count or search.plans >= FULL_PLANS or time.monotonic() > search.deadline:
            break
        result = search.attempt(seed, seen)
        if result:
            layout, motions = result
            found.append(
                {
                    "layout": layout,
                    "length_m": round(sum(m["length_m"] for m in motions), 3),
                    "clearance_m": min(m["clearance_m"] for m in motions),
                    "motions": motions,
                }
            )
    found.sort(key=lambda s: (s["length_m"], -s["clearance_m"]))
    error = None
    if not found:
        reason = f" Last check: {search.failure}" if search.failure else ""
        error = {
            "message": f"No feasible layout found after {search.plans} full checks.{reason}",
            "layer": "geometry",
        }
    return {"arm": ARM, "suggestions": found, "checked": search.plans, "error": error}
