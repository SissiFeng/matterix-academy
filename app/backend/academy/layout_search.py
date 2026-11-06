"""Enumerate feasible bench layouts for a saved workflow and measure each one.

Every transfer arm is placed first, then every station it serves on rings around it,
facing the arm. A layout counts only when `plan_workflow` finds every transfer. There is
no single objective: the search walks a fixed list of starting arrangements (first arm
position, bearing, ring and access order) and reports metrics for each layout found so
the user can compare them. The walk is chunked so each request stays inside the Lambda
limit; the client resumes from `next` until the list is exhausted or it stops.

Deterministic: the same inputs and start index always give the same layouts while a
chunk stays under its time cap. Synthetic geometry only, as checked by the planner.
"""

import itertools
import math
import time

from .mock_contract import PlanError, execute_mock
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
START_ANGLES = (0, 90, 180, 270)  # bearings a first station starts from
SIDES = ("top", "front")
ARM_GRID = 0.2
ARM_STARTS = 6  # nearest-centre positions a first arm starts from
SPARE_GRID = 0.1
MARGIN = 0.02  # reach kept in reserve so a pose is not at full stretch
ATTEMPT_PLANS = 4  # full workflow checks one starting arrangement may spend
CHUNK_PLANS = 16
CHUNK_SECONDS = 6.0
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


def _stretch(twins, arm, station):
    """Shoulder-to-flange distance at the station's pre-grasp pose."""
    spec = twins[station["twin_id"]]["spec"]
    point, direction, rotation = access(spec, station)
    flange = _add(_add(point, direction, APPROACH), rotation[2], -TOOL)
    base = mount(twins[arm["twin_id"]]["spec"], arm)
    return _norm(_sub(flange, _add(_col(base, 3), _col(base, 2), D[0])))


def _access_xz(twins, placement):
    point = access(twins[placement["twin_id"]]["spec"], placement)[0]
    return point[0], point[2]


def _distinct(a, b):
    where = {p["twin_id"]: (p["x"], p["z"]) for p in b}
    return any(math.dist((p["x"], p["z"]), where[p["twin_id"]]) >= DISTINCT for p in a)


class Search:
    def __init__(self, twins, bench, steps, fixed):
        self.twins, self.bench, self.steps = twins, bench, steps
        self.fixed = {p["twin_id"]: {**p, "kept": True} for p in fixed}
        self.transfers = [s for s in steps if s["operation"] == "transfer"]
        if not self.transfers:
            raise PlanError("state", "Save a workflow with a transfer step to search for a layout")
        self.arms = list(dict.fromkeys(s["device_id"] for s in self.transfers))
        self.serving, uses = {}, {}
        for s in self.transfers:
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
        self.free_arms = [a for a in self.arms if a not in self.fixed]
        trace = execute_mock(twins, steps)
        # The mock books one second per transfer; the arm estimate replaces it.
        self.device_s = trace[-1]["elapsed_s"] - len(self.transfers)
        self.plans = 0
        self.failure = None
        self.reach_cache = {}
        validate_layout(twins, self.layout(self.fixed.values()))
        arms = len(self.arm_grid(self.free_arms[0], [])) if self.free_arms else 1
        self.starts = list(
            itertools.product(
                range(min(ARM_STARTS, arms) or 1),
                range(len(RADII)),
                range(len(SIDES)),
                START_ANGLES,
            )
        )

    def layout(self, placements):
        keys = ("twin_id", "x", "z", "yaw", "access")
        return {
            "bench": self.bench,
            "placements": [
                {**{k: p[k] for k in keys}, "kept": p.get("kept", False)} for p in placements
            ],
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
            ok = _stretch(self.twins, arm, station) <= REACH - MARGIN
            if ok:
                planner = Planner(self.twins, self.layout([arm, station]), self.twins[arm_id])
                try:
                    planner.station(self.twins[station_id], {**planner.rest, GRIPPER: {station_id}})
                except PlanError as exc:
                    ok, self.failure = False, str(exc)
            self.reach_cache[key] = ok
        return self.reach_cache[key]

    def arm_grid(self, arm_id, placed):
        half = max(abs(v) for v in footprint(self.twins[arm_id]["spec"]))
        w, d = self.bench["width"] / 2 - half, self.bench["depth"] / 2 - half
        grid = [
            (round(i * ARM_GRID, 2) + 0.0, round(k * ARM_GRID, 2) + 0.0)
            for i in range(-int(w / ARM_GRID), int(w / ARM_GRID) + 1)
            for k in range(-int(d / ARM_GRID), int(d / ARM_GRID) + 1)
        ]
        grid.sort(key=lambda p: (math.hypot(*p), p))
        others = [_base(self.twins, p) for p in placed if p["twin_id"] in self.arms]
        poses = []
        for x, z in grid:
            pose = {"twin_id": arm_id, "x": x, "z": z, "yaw": 0, "access": "top"}
            base = _base(self.twins, pose)
            if any(math.dist(base, o) < 0.6 for o in others):
                continue
            # Kept stations this arm serves must stay within its reach.
            if any(
                arm_id in self.serving[t]
                and math.dist(base, _access_xz(self.twins, self.fixed[t])) > REACH
                for t in self.fixed
                if t in self.serving
            ):
                continue
            if self.fits(arm_id, pose, placed):
                poses.append(pose)
        return poses

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

    def spare_pose(self, twin_id, placed):
        """Instruments outside the workflow go where the arms are least likely to be."""
        bases = [_base(self.twins, p) for p in placed if p["twin_id"] in self.arms]
        w, d = self.bench["width"] / 2, self.bench["depth"] / 2
        grid = [
            (round(i * SPARE_GRID, 2) + 0.0, round(k * SPARE_GRID, 2) + 0.0)
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

    def shape(self, placements):
        """The arrangement up to moving or turning the whole cell on the bench.

        Ring distance and access side of each station, and the bearings between stations
        around the same arm; spare instruments do not count.
        """
        places = {p["twin_id"]: p for p in placements}
        bearings, rings = {}, []
        for station, arms in sorted(self.serving.items()):
            home = places[arms[0]]
            bx, bz = _base(self.twins, home)
            px, pz = _access_xz(self.twins, places[station])
            rings.append(
                (station, round(math.dist((bx, bz), (px, pz)) / 0.05), places[station]["access"])
            )
            bearings.setdefault(arms[0], []).append(math.degrees(math.atan2(px - bx, pz - bz)))
        turns = tuple(
            round(((b - a + 180) % 360 - 180) / 15)
            for angles in bearings.values()
            for a, b in itertools.combinations(angles, 2)
        )
        spans = tuple(
            round(math.dist(_base(self.twins, places[a]), _base(self.twins, places[b])) / 0.1)
            for a, b in itertools.combinations(self.arms, 2)
        )
        return tuple(rings), turns, spans

    def distinct(self, a, b):
        # Kept instruments pin the cell to the bench, so a moved arm is a new layout.
        if self.fixed:
            return _distinct(a, b)
        return self.shape(a) != self.shape(b)

    def metrics(self, layout, motions):
        places = {p["twin_id"]: p for p in layout["placements"]}
        stretch = max(
            _stretch(self.twins, places[s["device_id"]], places[s[k]])
            for s in self.transfers
            for k in ("source_id", "target_id")
        )
        xs, zs = zip(
            *(
                c
                for p in layout["placements"]
                for c in corners(self.twins[p["twin_id"]]["spec"], p)
            ),
            strict=True,
        )
        arm_s = sum(m["seconds"] for m in motions)
        return {
            "run_s": round(self.device_s + arm_s, 1),
            "arm_s": round(arm_s, 1),
            "path_m": round(sum(m["length_m"] for m in motions), 3),
            "clearance_m": min(m["clearance_m"] for m in motions),
            "reach_margin_m": round(REACH - stretch, 3),
            "area_m2": round((max(xs) - min(xs)) * (max(zs) - min(zs)), 2),
        }

    def attempt(self, start, deadline, plans_left, seen):
        arm_rank, radius_shift, side_shift, angle = start
        order = {
            "angle": angle,
            "radii": RADII[radius_shift:] + RADII[:radius_shift],
            "sides": SIDES[side_shift:] + SIDES[:side_shift],
        }
        budget = [min(ATTEMPT_PLANS, plans_left)]

        def place(placed, arms, stations):
            if time.monotonic() > deadline or not budget[0]:
                return None
            if arms:
                poses = self.arm_grid(arms[0], placed)
                if len(arms) == len(self.free_arms):
                    poses = poses[arm_rank:] + poses[:arm_rank]
                for pose in poses:
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
                pose = self.spare_pose(twin_id, full)
                if pose is None:
                    name = self.twins[twin_id]["spec"]["name"]
                    self.failure = f"No room left on the bench for {name}"
                    return None
                full.append(pose)
            if any(not self.distinct(full, other) for other in seen):
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
            return {"layout": layout, **self.metrics(layout, motions), "motions": motions}

        return place(list(self.fixed.values()), self.free_arms, self.stations)


def search_layouts(twins, bench, steps, fixed=(), start=0, avoid=(), seconds=CHUNK_SECONDS):
    """One chunk of the enumeration, from starting arrangement `start` onward.

    `avoid` holds layouts earlier chunks already returned, so they are not checked again.
    """
    search = Search(twins, bench, steps, fixed)
    deadline = time.monotonic() + seconds
    found = []
    seen = [list(placements) for placements in avoid]
    index = start
    while index < len(search.starts):
        if time.monotonic() > deadline or search.plans >= CHUNK_PLANS:
            break
        result = search.attempt(search.starts[index], deadline, CHUNK_PLANS - search.plans, seen)
        if not result and time.monotonic() > deadline:
            break  # cut short: the next chunk retries this arrangement
        index += 1
        if result:
            found.append(result)
    return {
        "arm": ARM,
        "total": len(search.starts),
        "next": index if index < len(search.starts) else None,
        "candidates": found,
        "checked": search.plans,
        "failure": search.failure,
    }
