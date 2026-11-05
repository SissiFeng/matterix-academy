"""Bench layout and link-level arm motion for teaching twins.

Every twin that performs `transfer` is modelled as a UR5e mounted on top of its own
parts. Links are capsules, instrument parts are yaw-rotated boxes and the bench is the
plane y = 0 (world is y-up, matching the twin parts). The planner is deterministic and
pure Python so the same layout always gets the same verdict on Lambda and locally.

Synthetic geometry only: no arm self-collision, dynamics, controller or calibrated
pose. A passing path is not motion-planning, Isaac/GPU or physical robot validation.
"""

import math
import random

from .mock_contract import PlanError

# Universal Robots' published UR5e DH parameters (metres, radians).
D = (0.1625, 0.0, 0.0, 0.1333, 0.0997, 0.0996)
A = (0.0, -0.425, -0.3922, 0.0, 0.0, 0.0)
ALPHA = (math.pi / 2, 0.0, 0.0, math.pi / 2, -math.pi / 2, 0.0)
ARM = "UR5e"
REACH = 0.85
TOOL = 0.16  # flange to grasp point: gripper holding the labware
LINKS = (
    ("base", 0.075),
    ("upper arm", 0.065),
    ("forearm", 0.055),
    ("wrist 1", 0.048),
    ("wrist 2", 0.048),
    ("wrist 3", 0.048),
    ("gripper", 0.06),
)
GRIPPER = len(LINKS) - 1
# Kept inside the UR5e SiLA connector's margins (elbow < 155°, others < 355°) so a
# planned path can be exported to it without angle wrapping.
LIMITS = tuple(math.radians(d) for d in (354, 354, 154, 354, 354, 354))
SAFETY = 0.01  # required clearance between any capsule and any obstacle
APPROACH = 0.12  # straight-line approach and retreat along the access direction
SAMPLE = 0.025  # capsule sampling spacing
JOINT_STEP = 0.05  # interpolation resolution in joint space
LIFT = 0.25
KEEP_FRAMES = 90
NOMINAL_SPEED = 20  # °/s, the UR5e connector's default, for runtime estimates


class MotionError(PlanError):
    def __init__(self, message, motions, attempt):
        super().__init__("geometry", message)
        self.motions = motions
        self.attempt = attempt


def _mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def _dh(theta, d, a, alpha):
    ct, st, ca, sa = math.cos(theta), math.sin(theta), math.cos(alpha), math.sin(alpha)
    return [
        [ct, -st * ca, st * sa, a * ct],
        [st, ct * ca, -ct * sa, a * st],
        [0, sa, ca, d],
        [0, 0, 0, 1],
    ]


def _col(t, j):
    return (t[0][j], t[1][j], t[2][j])


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b, k=1.0):
    return (a[0] + k * b[0], a[1] + k * b[1], a[2] + k * b[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a):
    return math.sqrt(a[0] ** 2 + a[1] ** 2 + a[2] ** 2)


def _yaw(yaw_deg, x, z):
    """Rotate a bench-plane vector about +y, the same convention three.js uses."""
    c, s = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))
    return c * x + s * z, -s * x + c * z


def frames(q, base):
    """World frames of the base, six joints and the grasp point."""
    out = [base]
    t = base
    for i in range(6):
        t = _mul(t, _dh(q[i], D[i], A[i], ALPHA[i]))
        out.append(t)
    out.append(_mul(t, [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, TOOL], [0, 0, 0, 1]]))
    return out


def points(q, base):
    return [_col(f, 3) for f in frames(q, base)]


def _solve6(m, v):
    m = [row[:] + [v[i]] for i, row in enumerate(m)]
    for c in range(6):
        p = max(range(c, 6), key=lambda r: abs(m[r][c]))
        m[c], m[p] = m[p], m[c]
        for r in range(c + 1, 6):
            f = m[r][c] / m[c][c]
            for k in range(c, 7):
                m[r][k] -= f * m[c][k]
    x = [0.0] * 6
    for r in range(5, -1, -1):
        x[r] = (m[r][6] - sum(m[r][k] * x[k] for k in range(r + 1, 6))) / m[r][r]
    return x


def solve_ik(position, rotation, seed, base):
    """Damped least squares to a full grasp pose; returns joint angles or None."""
    q = list(seed)
    for _ in range(80):
        fr = frames(q, base)
        tip = fr[7]
        ep = _sub(position, _col(tip, 3))
        er = (0.0, 0.0, 0.0)
        for k in range(3):
            er = _add(er, _cross(_col(tip, k), rotation[k]), 0.5)
        if _norm(ep) < 5e-4 and _norm(er) < 2e-3:
            return q
        e = [*ep, *er]
        jac = []
        for i in range(6):
            z, p = _col(fr[i], 2), _col(fr[i], 3)
            jac.append([*_cross(z, _sub(_col(tip, 3), p)), *z])  # column i
        jjt = [
            [
                sum(jac[k][r] * jac[k][c] for k in range(6)) + (0.0025 if r == c else 0)
                for c in range(6)
            ]
            for r in range(6)
        ]
        y = _solve6(jjt, e)
        dq = [sum(jac[i][r] * y[r] for r in range(6)) for i in range(6)]
        biggest = max(abs(v) for v in dq)
        if biggest > 0.4:
            dq = [v * 0.4 / biggest for v in dq]
        q = [max(-lim, min(lim, a + b)) for a, b, lim in zip(q, dq, LIMITS, strict=True)]
    return None


def _wrap(q):
    return [math.atan2(math.sin(a), math.cos(a)) for a in q]


def _span(a, b):
    return max(abs(x - y) for x, y in zip(a, b, strict=True))


class Box:
    __slots__ = ("twin_id", "name", "center", "half", "cos", "sin", "radius")

    def __init__(self, twin_id, name, center, half, yaw_deg):
        self.twin_id, self.name, self.center, self.half = twin_id, name, center, half
        self.cos, self.sin = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))
        self.radius = _norm(half)

    def distance(self, p):
        dx, dy, dz = _sub(p, self.center)
        local = (self.cos * dx - self.sin * dz, dy, self.sin * dx + self.cos * dz)
        out = [max(0.0, abs(v) - h) for v, h in zip(local, self.half, strict=True)]
        return _norm(out)


class Scene:
    def __init__(self, boxes):
        self.boxes = boxes

    def measure(self, pts, ignore):
        """Smallest clearance of the arm's capsules and what it is against."""
        worst = (math.inf, None, None)
        for li, (link, radius) in enumerate(LINKS):
            a, b = pts[li], pts[li + 1]
            seg = _sub(b, a)
            length = _norm(seg)
            n = max(1, math.ceil(length / SAMPLE))
            samples = [_add(a, seg, k / n) for k in range(n + 1)]
            floor = min(p[1] for p in samples) - radius
            if floor < worst[0]:
                worst = (floor, link, "the bench")
            mid = _add(a, seg, 0.5)
            skip = ignore.get(li, ())
            for box in self.boxes:
                if box.twin_id in skip:
                    continue
                bound = _norm(_sub(mid, box.center)) - length / 2 - radius - box.radius
                if bound > max(worst[0], SAFETY):
                    worst = min(worst, (bound, link, box.name), key=lambda w: w[0])
                    continue
                gap = min(box.distance(p) for p in samples) - radius
                if gap < worst[0]:
                    worst = (gap, link, box.name)
        return worst


def footprint(spec):
    """Local x/z extent of a twin's parts: (min_x, max_x, min_z, max_z)."""
    parts = spec["parts"]
    return (
        min(p["position"][0] - p["size"][0] / 2 for p in parts),
        max(p["position"][0] + p["size"][0] / 2 for p in parts),
        min(p["position"][2] - p["size"][2] / 2 for p in parts),
        max(p["position"][2] + p["size"][2] / 2 for p in parts),
    )


def top(spec):
    return max(p["position"][1] + p["size"][1] / 2 for p in spec["parts"])


def corners(spec, placement):
    x0, x1, z0, z1 = footprint(spec)
    out = []
    for x, z in ((x0, z0), (x1, z0), (x1, z1), (x0, z1)):
        rx, rz = _yaw(placement["yaw"], x, z)
        out.append((placement["x"] + rx, placement["z"] + rz))
    return out


def _overlap(a, b):
    for poly in (a, b):
        for i in range(2):
            ex, ez = poly[i + 1][0] - poly[i][0], poly[i + 1][1] - poly[i][1]
            axis = (-ez, ex)
            pa = [x * axis[0] + z * axis[1] for x, z in a]
            pb = [x * axis[0] + z * axis[1] for x, z in b]
            if max(pa) <= min(pb) + 1e-9 or max(pb) <= min(pa) + 1e-9:
                return False
    return True


def validate_layout(twins, layout):
    """Every placed footprint lies on the bench and no two footprints overlap."""
    half_w, half_d = layout["bench"]["width"] / 2, layout["bench"]["depth"] / 2
    shapes = []
    for placement in layout["placements"]:
        twin = twins[placement["twin_id"]]
        shape = corners(twin["spec"], placement)
        if any(abs(x) > half_w + 1e-9 or abs(z) > half_d + 1e-9 for x, z in shape):
            raise PlanError("geometry", f"{twin['spec']['name']} extends past the bench edge")
        for other, other_shape in shapes:
            if _overlap(shape, other_shape):
                raise PlanError(
                    "geometry", f"{twin['spec']['name']} overlaps {other['spec']['name']}"
                )
        shapes.append((twin, shape))


def _scene(twins, layout):
    boxes = []
    for placement in layout["placements"]:
        twin = twins[placement["twin_id"]]
        for part in twin["spec"]["parts"]:
            px, py, pz = part["position"]
            rx, rz = _yaw(placement["yaw"], px, pz)
            boxes.append(
                Box(
                    twin["id"],
                    twin["spec"]["name"],
                    (placement["x"] + rx, py, placement["z"] + rz),
                    tuple(v / 2 for v in part["size"]),
                    placement["yaw"],
                )
            )
    return Scene(boxes)


def mount(spec, placement):
    """The arm base frame on top of the transfer twin's footprint centre."""
    x0, x1, z0, z1 = footprint(spec)
    rx, rz = _yaw(placement["yaw"], (x0 + x1) / 2, (z0 + z1) / 2)
    x, y, z = placement["x"] + rx, top(spec), placement["z"] + rz
    c, s = math.cos(math.radians(placement["yaw"])), math.sin(math.radians(placement["yaw"]))
    # Yaw about world y, then the robot's z-up frame turned to y-up.
    return [[c, -s, 0, x], [0, 0, 1, y], [-s, -c, 0, z], [0, 0, 0, 1]]


def access(spec, placement):
    """Grasp point, approach direction and grasp rotation (as columns) of a station."""
    x0, x1, z0, z1 = footprint(spec)
    height = top(spec)
    yaw = placement["yaw"]
    if placement["access"] == "front":
        local = ((x0 + x1) / 2, max(0.08, height / 2), z1 + 0.04)
        nx, nz = _yaw(yaw, 0, 1)
        direction = (nx, 0.0, nz)
        tool_z = (-nx, 0.0, -nz)
        tool_x = (0.0, 1.0, 0.0)
    else:
        local = ((x0 + x1) / 2, height + 0.02, (z0 + z1) / 2)
        direction = (0.0, 1.0, 0.0)
        tool_z = (0.0, -1.0, 0.0)
        ax, az = _yaw(yaw, 1, 0)
        tool_x = (ax, 0.0, az)
    rx, rz = _yaw(yaw, local[0], local[2])
    point = (placement["x"] + rx, local[1], placement["z"] + rz)
    return point, direction, (tool_x, _cross(tool_z, tool_x), tool_z)


def _seeds(base, target):
    local = _sub(target, _col(base, 3))
    # Robot-frame x/y are columns 0/1 of the base rotation.
    phi = math.atan2(
        sum(a * b for a, b in zip(local, _col(base, 1), strict=True)),
        sum(a * b for a, b in zip(local, _col(base, 0), strict=True)),
    )
    for q1 in (phi + math.pi, phi):
        for q3 in (math.pi / 2, -math.pi / 2, 2.6, -2.6, 0.4, -0.4):
            for q2 in (-math.pi / 2, -math.pi / 3, -2 * math.pi / 3):
                for q5 in (-math.pi / 2, math.pi / 2):
                    yield [q1, q2 if q3 > 0 else q2 + math.pi, q3, -math.pi / 2, q5, 0.0]


def _rotate(v, axis, angle):
    """Rodrigues rotation of v about a unit axis."""
    c, s = math.cos(angle), math.sin(angle)
    k = sum(a * b for a, b in zip(axis, v, strict=True)) * (1 - c)
    cross = _cross(axis, v)
    return tuple(v[i] * c + cross[i] * s + axis[i] * k for i in range(3))


def _spin(rotation, angle):
    """Swing about the vertical so atan2(z, x) grows by `angle`."""
    return tuple(_rotate(col, (0.0, -1.0, 0.0), angle) for col in rotation)


def _slerp(ra, rb):
    """Rotation interpolation between two grasp rotations given as world columns."""
    m = [[sum(rb[k][i] * ra[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    angle = math.acos(max(-1.0, min(1.0, (m[0][0] + m[1][1] + m[2][2] - 1) / 2)))
    if angle < 1e-6:
        return lambda t: ra
    if math.pi - angle < 1e-3:
        i = max(range(3), key=lambda j: m[j][j])
        ai = math.sqrt(max(0.0, (m[i][i] + 1) / 2))
        axis = tuple(ai if j == i else m[i][j] / (2 * ai) for j in range(3))
    else:
        s = 2 * math.sin(angle)
        axis = ((m[2][1] - m[1][2]) / s, (m[0][2] - m[2][0]) / s, (m[1][0] - m[0][1]) / s)
    return lambda t: tuple(_rotate(col, axis, angle * t) for col in ra)


def _straight(start, end, ra, rb=None):
    turn = _slerp(ra, rb or ra)
    length = _norm(_sub(end, start))
    return lambda t: (_add(start, _sub(end, start), t), turn(t)), length


def _arc(center, start, end, ra, rb, longway):
    """Tool path that swings around the arm's vertical base axis at changing radius."""
    fa = math.atan2(start[2] - center[2], start[0] - center[0])
    fb = math.atan2(end[2] - center[2], end[0] - center[0])
    ra_h = math.hypot(start[0] - center[0], start[2] - center[2])
    rb_h = math.hypot(end[0] - center[0], end[2] - center[2])
    sweep = math.atan2(math.sin(fb - fa), math.cos(fb - fa))
    if longway:
        sweep -= math.copysign(2 * math.pi, sweep)
    turn = _slerp(ra, _spin(rb, -sweep))

    def pose(t):
        f, r = fa + sweep * t, ra_h + (rb_h - ra_h) * t
        point = (
            center[0] + r * math.cos(f),
            start[1] + (end[1] - start[1]) * t,
            center[2] + r * math.sin(f),
        )
        return point, _spin(turn(t), sweep * t)

    return pose, abs(sweep) * max(ra_h, rb_h) + abs(end[1] - start[1])


class Planner:
    def __init__(self, twins, layout, actor):
        self.places = {p["twin_id"]: p for p in layout["placements"]}
        self.scene = _scene(twins, layout)
        self.base = mount(actor["spec"], self.places[actor["id"]])
        self.name = actor["spec"]["name"]
        self.rest = {0: {actor["id"]}}  # the base capsule sits on its own pedestal

    def measure(self, q, ignore=None):
        return self.scene.measure(points(q, self.base), ignore or self.rest)

    def candidates(self, position, rotation, ignore, prefer=None):
        found, hits = [], []
        seeds = _seeds(self.base, position)
        for seed in [prefer, *seeds] if prefer else seeds:
            q = solve_ik(position, rotation, seed, self.base)
            if q is None:
                continue
            q = _wrap(q)
            if any(_span(q, f) < 0.05 for f in found):
                continue
            clear = self.measure(q, ignore)
            if clear[0] < SAFETY:
                hits.append(clear)
                continue
            found.append(q)
            if len(found) >= 4:
                break
        if prefer:
            found.sort(key=lambda f: _span(f, prefer))
        # Name another instrument before the arm's own pedestal or the bench.
        hits.sort(key=lambda h: (h[2] == self.name, h[2] == "the bench"))
        return found, hits[0] if hits else None

    def follow(self, q, path, ignore=None):
        """Track a tool path with continuous joint angles.

        Returns (joints, clearance, None) or (None, hit, partial joints); a hit of None
        means the arm cannot follow the path without a wrist flip or leaving its workspace.
        """
        pose, length = path
        steps = max(
            1, math.ceil(length / 0.015), math.ceil(_span(pose(0)[1][0], pose(1)[1][0]) / 0.05)
        )
        joints, worst = [q], math.inf
        for k in range(1, steps + 1):
            point, rotation = pose(k / steps)
            nxt = solve_ik(point, rotation, q, self.base)
            if nxt is None or _span(nxt, q) > 0.35:
                return None, None, joints
            clear = self.measure(nxt, ignore)
            if clear[0] < SAFETY:
                return None, clear, [*joints, nxt]
            worst = min(worst, clear[0])
            joints.append(nxt)
            q = nxt
        return joints, worst, None

    def edge(self, a, b, ignore=None, step=JOINT_STEP):
        n = max(1, math.ceil(_span(a, b) / step))
        path, worst = [], math.inf
        for k in range(1, n + 1):
            q = [x + (y - x) * k / n for x, y in zip(a, b, strict=True)]
            clear = self.measure(q, ignore)
            if clear[0] < SAFETY:
                return None, clear, [*path, q]
            worst = min(worst, clear[0])
            path.append(q)
        return path, worst, None

    def rrt_connect(self, start, goal, seed):
        rng = random.Random(seed)
        a, b = ([start], [None]), ([goal], [None])

        def extend(tree, target):
            nodes, parents = tree
            i = min(range(len(nodes)), key=lambda j: _span(nodes[j], target))
            span = _span(nodes[i], target)
            if span <= 0.3:
                q = target
            else:
                q = [x + (y - x) * 0.3 / span for x, y in zip(nodes[i], target, strict=True)]
            if self.edge(nodes[i], q)[0] is None:
                return None
            nodes.append(q)
            parents.append(i)
            return len(nodes) - 1

        def branch(tree, i):
            nodes, parents = tree
            out = []
            while i is not None:
                out.append(nodes[i])
                i = parents[i]
            return out

        for _ in range(300):
            ia = extend(a, [rng.uniform(-min(lim, math.pi), min(lim, math.pi)) for lim in LIMITS])
            if ia is not None:
                while (ib := extend(b, a[0][ia])) is not None:
                    if _span(b[0][ib], a[0][ia]) < 1e-9:
                        path = branch(a, ia)[::-1] + branch(b, ib)[1:]
                        return self.shortcut(path if path[0] is start else path[::-1], rng)
            a, b = b, a
        return None

    def shortcut(self, path, rng):
        for _ in range(40):
            if len(path) < 3:
                break
            i, j = sorted(rng.sample(range(len(path)), 2))
            if j - i > 1 and self.edge(path[i], path[j])[0] is not None:
                path = path[: i + 1] + path[j:]
        dense = [path[0]]
        for x, y in zip(path, path[1:], strict=False):
            dense += self.edge(x, y)[0]
        return dense

    def station(self, twin, ignore, prefer=None):
        """Collision-free configurations at a station's pre-grasp pose with a clear approach."""
        spec = twin["spec"]
        point, direction, rotation = access(spec, self.places[twin["id"]])
        pre = _add(point, direction, APPROACH)
        found, blocked = self.candidates(pre, rotation, ignore, prefer)
        reason = f"the {blocked[1]} would hit {blocked[2]}" if blocked else None
        if not found and not blocked:
            flange = _add(pre, rotation[2], -TOOL)
            shoulder = _add(_col(self.base, 3), _col(self.base, 2), D[0])
            distance = _norm(_sub(flange, shoulder))
            reason = (
                f"it is {distance:.2f} m from the {ARM} shoulder and the arm reaches about {REACH:.2f} m"
                if distance > REACH
                else f"the {ARM} cannot hold the gripper in that orientation there"
            )
        options = []
        for q in found:
            joints, clear, _ = self.follow(q, _straight(pre, point, rotation), ignore)
            if joints:
                options.append((q, joints, clear))
            else:
                reason = (
                    f"the {clear[1]} would hit {clear[2]} on the way in"
                    if clear
                    else "the straight approach needs a wrist flip"
                )
        if not options:
            side = self.places[twin["id"]]["access"]
            raise PlanError("geometry", f"{spec['name']}'s {side} access point: {reason}")
        return options, pre, rotation, point

    def swing(self, qa, pa, ra, pb, rb, target_ignore, grasp):
        """Lift, swing around the base at travel height, lower and approach."""
        center = _col(self.base, 3)
        first = None
        for travel in (0.15, 0.35):
            height = max(pa[1], pb[1]) + travel
            up_a, up_b = (pa[0], height, pa[2]), (pb[0], height, pb[2])
            lift = self.follow(qa, _straight(pa, up_a, ra))
            if lift[0] is None:
                first = first or lift
                continue
            for longway in (False, True):
                sweep = self.follow(lift[0][-1], _arc(center, up_a, up_b, ra, rb, longway))
                if sweep[0] is None:
                    first = first or (None, sweep[1], lift[0] + sweep[2])
                    continue
                lower = self.follow(sweep[0][-1], _straight(up_b, pb, rb))
                if lower[0] is None:
                    first = first or (None, lower[1], lift[0] + sweep[0] + lower[2])
                    continue
                enter = self.follow(lower[0][-1], _straight(pb, grasp, rb), target_ignore)
                if enter[0] is None:
                    continue
                return (
                    lift[0] + sweep[0][1:] + lower[0][1:],
                    min(lift[1], sweep[1], lower[1]),
                    enter[0],
                    enter[1],
                ), None
        return None, first


def _rounded(pts):
    return [[round(v, 4) for v in p] for p in pts]


def _thin(seq):
    keep = max(1, math.ceil(len(seq) / KEEP_FRAMES))
    return seq[::keep] + ([seq[-1]] if (len(seq) - 1) % keep else [])


def plan_transfer(twins, layout, step_no, step):
    actor, source, target = (twins[step[k]] for k in ("device_id", "source_id", "target_id"))
    places = {p["twin_id"] for p in layout["placements"]}
    for twin in (actor, source, target):
        if twin["id"] not in places:
            raise PlanError(
                "geometry", f"Step {step_no}: place {twin['spec']['name']} on the bench in Layout"
            )
    planner = Planner(twins, layout, actor)
    label = f"Step {step_no}"
    src_ignore = {**planner.rest, GRIPPER: {source["id"]}}
    tgt_ignore = {**planner.rest, GRIPPER: {target["id"]}}
    try:
        src_options, src_pre, src_rot, _ = planner.station(source, src_ignore)
        tgt_options, tgt_pre, tgt_rot, tgt_point = planner.station(
            target, tgt_ignore, prefer=src_options[0][0]
        )
    except PlanError as exc:
        raise PlanError("geometry", f"{label}: {exc}") from exc

    def motion(kind, pick, pick_clear, transit, transit_clear, place, place_clear):
        joints = pick + pick[::-1][1:] + transit[1:] + place[1:] + place[::-1][1:]
        frames_ = [points(q, planner.base) for q in joints]
        length = sum(_norm(_sub(b[-1], a[-1])) for a, b in zip(frames_, frames_[1:], strict=False))
        return {
            "step": step_no,
            "actor_id": actor["id"],
            "source_id": source["id"],
            "target_id": target["id"],
            "arm": ARM,
            "planner": kind,
            "length_m": round(length, 3),
            "clearance_m": round(min(pick_clear, transit_clear, place_clear), 3),
            # Joints move together, so each sample takes its largest joint change.
            "seconds": round(
                sum(_span(a, b) for a, b in zip(joints, joints[1:], strict=False))
                / math.radians(NOMINAL_SPEED)
                + 2 * DWELL,
                1,
            ),
            "frames": [_rounded(f) for f in _thin(frames_)],
            # Full-resolution joints for export; never stored or returned.
            "_chain": {
                "planner": planner,
                "segments": [
                    (f"Lower into {source['spec']['name']}", pick, src_ignore),
                    (f"Lift from {source['spec']['name']}", pick[::-1], src_ignore),
                    (f"Transit to {target['spec']['name']}", transit, None),
                    (f"Lower into {target['spec']['name']}", place, tgt_ignore),
                    (f"Retreat from {target['spec']['name']}", place[::-1], tgt_ignore),
                ],
            },
        }

    failure = None
    for qa, pick, pick_clear in src_options[:3]:
        found, miss = planner.swing(qa, src_pre, src_rot, tgt_pre, tgt_rot, tgt_ignore, tgt_point)
        if found:
            transit, transit_clear, place, place_clear = found
            return motion("swing", pick, pick_clear, transit, transit_clear, place, place_clear)
        failure = failure or miss
    # Fall back to joint space between known-good station configurations: straight,
    # then through an upright pose above the base, then a sampled search.
    for qa, pick, pick_clear in src_options[:3]:
        for qb, place, place_clear in tgt_options[:3]:
            dense, clear, _ = planner.edge(qa, qb)
            kind = "joint"
            if dense is None:
                upright = [[q[0], -math.pi / 2, 0.0, q[3], q[4], q[5]] for q in (qa, qb)]
                legs = [
                    planner.edge(a, b) for a, b in zip([qa, *upright], [*upright, qb], strict=True)
                ]
                if all(leg[0] is not None for leg in legs):
                    dense = [q for leg in legs for q in leg[0]]
                    clear = min(leg[1] for leg in legs)
                    kind = "upright"
            if dense is None:
                dense = planner.rrt_connect(qa, qb, f"{step_no}:{source['id']}:{target['id']}")
                kind = "rrt_connect"
                clear = None if dense is None else min(planner.measure(q)[0] for q in dense)
            if dense is not None:
                return motion(kind, pick, pick_clear, [qa, *dense], clear, place, place_clear)
    _, hit, attempt = failure or (None, None, [src_options[0][0]])
    blocker = (
        f"; the {hit[1]} hits {hit[2]}"
        if hit
        else "; the arm cannot stay continuous within the UR5e joint limits (elbow ±155°, others ±355°)"
    )
    raise MotionError(
        f"{label}: no collision-free path from {source['spec']['name']} to "
        f"{target['spec']['name']}{blocker}",
        [],
        {
            "step": step_no,
            "actor_id": actor["id"],
            "source_id": source["id"],
            "target_id": target["id"],
            "arm": ARM,
            "blocked_by": hit[2] if hit else None,
            "link": hit[1] if hit else None,
            "frames": [_rounded(points(q, planner.base)) for q in _thin(attempt)],
        },
    )


def plan_workflow(twins, layout, steps, keep_frames=False):
    """Motions for every transfer step; raises PlanError('geometry') on the first failure."""
    validate_layout(twins, layout)
    motions = []
    for index, step in enumerate(steps):
        if step["operation"] != "transfer":
            continue
        try:
            planned = plan_transfer(twins, layout, index + 1, step)
        except MotionError as exc:
            exc.motions = motions
            raise
        except PlanError as exc:
            # Keep the paths already planned so a preview can still show them.
            raise MotionError(str(exc), motions, None) from exc
        planned.pop("_chain")
        if not keep_frames:
            planned.pop("frames")
        motions.append(planned)
    return motions


CHAIN_LIMIT = 24  # waypoints the connector's Action Composer accepts
CHAIN_SECONDS = 120
HOLD = (
    0.01  # a nonzero hold makes every connector segment rest-to-rest, i.e. straight in joint space
)
DWELL = 1.0
EXPORT_STEP = 0.005  # rad


def _seconds(a, b, speed):
    """The connector's rest-to-rest quintic estimate for one segment, in seconds.

    Its automatic timing keeps 20 % of the speed cap in reserve for pausing.
    """
    distance = max(abs(math.degrees(x - y)) for x, y in zip(a, b, strict=True))
    speed *= 0.8
    # The connector then rounds and re-checks; 5 % covers what it adds in practice.
    return 1.05 * max(
        1.0, 1.03 * 1.875 * distance / speed, 1.03 * math.sqrt(5.774 * distance / (2 * speed))
    )


def action_chain(twins, layout, steps, step_no, speed):
    """Export one planned transfer as a `ur5e.action-chain/2` document.

    Dense planner joints are reduced to the fewest waypoints whose straight joint-space
    segments stay collision-free; every waypoint holds, so the connector's quintic
    interpolation follows exactly those checked segments.
    """
    validate_layout(twins, layout)
    if not 0 < step_no <= len(steps) or steps[step_no - 1]["operation"] != "transfer":
        raise PlanError("state", f"Step {step_no} is not a transfer")
    planned = plan_transfer(twins, layout, step_no, steps[step_no - 1])
    planner = planned["_chain"]["planner"]
    segments = planned["_chain"]["segments"]
    reference = segments[0][1][0]
    rows, previous = [], reference
    for label, joints, ignore in segments:
        if len(joints) < 2:
            continue
        kept, i = [], 0
        while i < len(joints) - 1:
            j = len(joints) - 1
            # Checked finer than planning so the connector's 125 Hz samples keep clearance.
            while j > i + 1 and planner.edge(joints[i], joints[j], ignore, EXPORT_STEP)[0] is None:
                j -= 1
            kept.append(joints[j])
            i = j
        for n, q in enumerate(kept, 1):
            last = n == len(kept)
            grasp = last and label.startswith("Lower into")
            rows.append(
                {
                    "name": (label if len(kept) == 1 else f"{label} {n}/{len(kept)}")[:60],
                    "degrees": [round(math.degrees(v), 4) for v in q],
                    "hold": DWELL if grasp else HOLD,
                }
            )
    if len(rows) > CHAIN_LIMIT:
        raise PlanError(
            "geometry",
            f"Step {step_no} needs {len(rows)} waypoints; the UR5e connector accepts {CHAIN_LIMIT}",
        )
    seconds = 0.0
    for row in rows:
        q = [math.radians(v) for v in row["degrees"]]
        seconds += _seconds(previous, q, speed) + row["hold"]
        previous = q
    if seconds > CHAIN_SECONDS:
        raise PlanError(
            "constraint",
            f"Step {step_no} needs about {seconds:.0f} s at {speed:g}°/s; the connector allows "
            f"{CHAIN_SECONDS} s per action. Choose a higher speed.",
        )
    return {
        "schema": "ur5e.action-chain/2",
        "timing_mode": "automatic",
        "units": "degrees",
        "reference": [round(math.degrees(v), 4) for v in reference],
        "speed": speed,
        "waypoints": rows,
        "provenance": {
            "generator": "Lab Onboarding bench layout",
            "evidence": "synthetic",
            "step": step_no,
            "source_id": planned["source_id"],
            "target_id": planned["target_id"],
            "tcp": [0.0, 0.0, TOOL, 0.0, 0.0, 0.0],
            "estimated_seconds": round(seconds, 1),
            "clearance_m": planned["clearance_m"],
            "note": (
                "Start at the reference pose (above the source). Joint angles use the nominal "
                "UR5e DH base frame; the path was checked against capsule links and box "
                "instruments only. No gripper commands, calibration, self-collision or "
                "dynamics. Not qualified for a physical robot."
            ),
        },
    }
