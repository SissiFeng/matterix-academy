import {
  armProfiles,
  type Access,
  type Layout,
  type Placement,
  type Twin,
  type TwinSpec,
} from "./instrumentTypes";

/** Mirrors workcell_layout.py; the server's check is authoritative. */
export const ARM_RADII = [0.075, 0.065, 0.055, 0.048, 0.048, 0.048, 0.06];
export const REACH = 0.85;
/** ANSI/SLAS plate footprint, drawn for each deck slot. */
export const SLOT: Point = [0.128, 0.086];
export type Point = [number, number];

export function rotate(yawDeg: number, x: number, z: number): Point {
  const r = (yawDeg * Math.PI) / 180;
  const c = Math.cos(r);
  const s = Math.sin(r);
  return [c * x + s * z, -s * x + c * z];
}

export function footprint(spec: TwinSpec) {
  const lo = (axis: 0 | 2) =>
    Math.min(...spec.parts.map((p) => p.position[axis] - p.size[axis] / 2));
  const hi = (axis: 0 | 2) =>
    Math.max(...spec.parts.map((p) => p.position[axis] + p.size[axis] / 2));
  return { x0: lo(0), x1: hi(0), z0: lo(2), z1: hi(2) };
}

export function top(spec: TwinSpec) {
  return Math.max(...spec.parts.map((p) => p.position[1] + p.size[1] / 2));
}

/** Mirrors workcell_layout.mount: the arm base frame (Z up) on top of its base plate, as a Y-up world matrix. */
export function mountMatrix(
  spec: TwinSpec,
  p: Pick<Placement, "x" | "z" | "yaw">,
) {
  const { x0, x1, z0, z1 } = footprint(spec);
  const [rx, rz] = rotate(p.yaw, (x0 + x1) / 2, (z0 + z1) / 2);
  const r = (p.yaw * Math.PI) / 180;
  const c = Math.cos(r);
  const s = Math.sin(r);
  // Row-major, as Matrix4.set takes it.
  return [
    c,
    -s,
    0,
    p.x + rx,
    0,
    0,
    1,
    top(spec),
    -s,
    -c,
    0,
    p.z + rz,
    0,
    0,
    0,
    1,
  ];
}

export function corners(spec: TwinSpec, p: Placement): Point[] {
  const { x0, x1, z0, z1 } = footprint(spec);
  return (
    [
      [x0, z0],
      [x1, z0],
      [x1, z1],
      [x0, z1],
    ] as Point[]
  ).map(([x, z]) => {
    const [rx, rz] = rotate(p.yaw, x, z);
    return [p.x + rx, p.z + rz];
  });
}

export function centre(spec: TwinSpec, p: Placement): Point {
  const { x0, x1, z0, z1 } = footprint(spec);
  const [rx, rz] = rotate(p.yaw, (x0 + x1) / 2, (z0 + z1) / 2);
  return [p.x + rx, p.z + rz];
}

/** The side labware goes in: the twin's own, or the placement's where the twin has none. */
export function loads(spec: TwinSpec, p?: Placement): Access {
  return spec.access ?? p?.access ?? "top";
}

const TRAY = 0.08; // mirrors workcell_layout.TRAY

/** Where an instrument without slots presents its tray, in front of its face. */
export function frontFace(spec: TwinSpec, p: Placement): Point {
  const { x0, x1, z1 } = footprint(spec);
  const [rx, rz] = rotate(p.yaw, (x0 + x1) / 2, z1 + TRAY);
  return [p.x + rx, p.z + rz];
}

export function overlaps(a: Point[], b: Point[]) {
  for (const poly of [a, b])
    for (let i = 0; i < 2; i++) {
      const axis: Point = [
        -(poly[i + 1][1] - poly[i][1]),
        poly[i + 1][0] - poly[i][0],
      ];
      const pa = a.map(([x, z]) => x * axis[0] + z * axis[1]);
      const pb = b.map(([x, z]) => x * axis[0] + z * axis[1]);
      if (
        Math.max(...pa) <= Math.min(...pb) + 1e-9 ||
        Math.max(...pb) <= Math.min(...pa) + 1e-9
      )
        return false;
    }
  return true;
}

/** Twin ids whose footprints overlap another or leave the bench. */
export function conflicts(layout: Layout, specs: Map<string, TwinSpec>) {
  const shapes = layout.placements.flatMap((p) => {
    const spec = specs.get(p.twin_id);
    return spec ? [{ id: p.twin_id, shape: corners(spec, p) }] : [];
  });
  const bad = new Set<string>();
  const { width, depth } = layout.bench;
  for (const [i, a] of shapes.entries()) {
    if (
      a.shape.some(
        ([x, z]) =>
          Math.abs(x) > width / 2 + 1e-9 || Math.abs(z) > depth / 2 + 1e-9,
      )
    )
      bad.add(a.id);
    for (const b of shapes.slice(i + 1))
      if (overlaps(a.shape, b.shape)) {
        bad.add(a.id);
        bad.add(b.id);
      }
  }
  return bad;
}

export const isArm = (twin: Pick<Twin, "spec">) =>
  !!twin.spec?.operations.includes("transfer");

const NEAR = 0.15; // arm base to the nearest edge of a station
const GAP = 0.06; // between neighbouring stations
const FIRST = 0.42; // nearest access point the layout search tries
const BENCH = { width: 2.4, depth: 1.6 };

/** A station facing `toward`, where it is served `radius` away at `bearing`: its tray or its centre. */
function facing(
  spec: TwinSpec,
  toward: Point,
  radius: number,
  bearing: number,
) {
  const point: Point = [
    toward[0] + Math.cos(bearing) * radius,
    toward[1] + Math.sin(bearing) * radius,
  ];
  // Mirrors layout_search._pose: the station's front (+z) is turned toward the arm, to
  // the nearest quarter turn so every instrument stands square to the bench.
  const exact =
    (Math.atan2(toward[0] - point[0], toward[1] - point[1]) * 180) / Math.PI;
  let yaw = (((Math.round(exact / 90) * 90) % 360) + 360) % 360;
  if (yaw > 180) yaw -= 360;
  const { x0, x1, z0, z1 } = footprint(spec);
  const [rx, rz] = rotate(
    yaw,
    (x0 + x1) / 2,
    loads(spec) === "front" ? z1 + TRAY : (z0 + z1) / 2,
  );
  const round = (v: number) => Number(v.toFixed(2)) + 0;
  return { x: round(point[0] - rx), z: round(point[1] - rz), yaw };
}

/** Stations around one arm, front first, each facing it and clear of its neighbours. */
function around(stations: Twin[], arm: Point, base: Point[]): Placement[] {
  if (!stations.length) return [];
  const size = stations.map((t) => {
    const { x0, x1, z0, z1 } = footprint(t.spec!);
    // How far the footprint comes toward the arm from where it is served.
    const near = loads(t.spec!) === "front" ? 0 : (z1 - z0) / 2;
    return { w: x1 - x0, near };
  });
  // One ring for every station: far enough that the deepest one clears the arm.
  let radius = Math.max(FIRST, ...size.map((s) => s.near + NEAR));
  const span = (r: number) =>
    size.map(({ w, near }) => 2 * Math.atan((w / 2 + GAP / 2) / (r - near)));
  while (span(radius).reduce((a, b) => a + b, 0) > 2 * Math.PI) radius += 0.05;
  const place = (r: number): Placement[] => {
    const angles = span(r);
    let bearing = Math.PI / 2 - angles.reduce((a, b) => a + b, 0) / 2;
    return stations.map((t, i) => {
      const centre = bearing + angles[i] / 2;
      bearing += angles[i];
      return {
        twin_id: t.id,
        ...facing(t.spec!, arm, r, centre),
        access: loads(t.spec!),
      };
    });
  };
  // Standing square rather than facing the arm exactly, a station's corner can reach
  // its neighbour or the space around the arm's base; the ring widens until none does.
  const pedestal: Point[] = [
    [arm[0] - NEAR, arm[1] - NEAR],
    [arm[0] + NEAR, arm[1] - NEAR],
    [arm[0] + NEAR, arm[1] + NEAR],
    [arm[0] - NEAR, arm[1] + NEAR],
  ];
  const clear = (placed: Placement[]) => {
    const shapes = placed.map((p, i) => corners(stations[i].spec!, p));
    return shapes.every(
      (a, i) =>
        !overlaps(a, pedestal) &&
        !overlaps(a, base) &&
        shapes.slice(i + 1).every((b) => !overlaps(a, b)),
    );
  };
  let placed = place(radius);
  // Six metres is past any bench; the server reports what still does not fit.
  for (let n = 0; n < 120 && !clear(placed); n++)
    placed = place((radius += 0.05));
  return placed;
}

/**
 * A starting layout: each arm with its share of the stations on a ring around it, every
 * station facing the arm. The server checks reach; layout search explores the rest.
 */
export function defaultLayout(twins: Twin[]): Layout {
  const arms = twins.filter(isArm);
  const stations = twins.filter((t) => !isArm(t));
  if (!arms.length) {
    const placements: Placement[] = [];
    let x = 0;
    for (const t of stations) {
      const { x0, x1 } = footprint(t.spec!);
      placements.push({
        twin_id: t.id,
        x: Number((x - x0).toFixed(2)),
        z: 0,
        yaw: 0,
        access: loads(t.spec!),
      });
      x += x1 - x0 + GAP;
    }
    const shift = x / 2;
    placements.forEach((p) => (p.x = Number((p.x - shift).toFixed(2))));
    return fit({ bench: BENCH, placements }, twins);
  }
  // Consecutive stations share an arm, as consecutive steps usually do.
  const share = Math.ceil(stations.length / arms.length);
  const groups = arms.map((_, i) => stations.slice(i * share, (i + 1) * share));
  const specs = new Map(twins.map((t) => [t.id, t.spec!]));
  const cells = arms.map((arm, i) => {
    const home = {
      twin_id: arm.id,
      x: 0,
      z: 0,
      yaw: 0,
      access: "top" as const,
    };
    const placed = [
      home,
      ...around(groups[i], [0, 0], corners(arm.spec!, home)),
    ];
    const xs = placed.flatMap((p) =>
      corners(specs.get(p.twin_id)!, p).map((c) => c[0]),
    );
    return { placed, lo: Math.min(...xs), hi: Math.max(...xs) };
  });
  // Cells side by side along x, centred on the bench.
  const width =
    cells.reduce((a, c) => a + c.hi - c.lo, 0) + GAP * (cells.length - 1);
  let left = -width / 2;
  const placements = cells.flatMap((c) => {
    const dx = left - c.lo;
    left += c.hi - c.lo + GAP;
    return c.placed.map((p) => ({
      ...p,
      x: Number((p.x + dx).toFixed(2)) + 0,
    }));
  });
  return fit({ bench: BENCH, placements }, twins);
}

/** The arrangement centred on a bench grown, in 10 cm steps, to hold every footprint. */
function fit(layout: Layout, twins: Twin[]): Layout {
  const specs = new Map(twins.map((t) => [t.id, t.spec!]));
  const shape = (ps: Placement[]) =>
    ps.flatMap((p) => corners(specs.get(p.twin_id)!, p));
  const before = shape(layout.placements);
  const mid = (axis: 0 | 1) =>
    before.length
      ? (Math.min(...before.map((c) => c[axis])) +
          Math.max(...before.map((c) => c[axis]))) /
        2
      : 0;
  const [dx, dz] = [mid(0), mid(1)];
  const placements = layout.placements.map((p) => ({
    ...p,
    x: Number((p.x - dx).toFixed(2)) + 0,
    z: Number((p.z - dz).toFixed(2)) + 0,
  }));
  const all = shape(placements);
  const half = (axis: 0 | 1) =>
    Math.max(0, ...all.map((c) => Math.abs(c[axis])));
  const grow = (need: number, min: number) =>
    Math.max(min, Math.ceil((2 * need + 0.1) * 10) / 10);
  return {
    bench: {
      width: grow(half(0), layout.bench.width),
      depth: grow(half(1), layout.bench.depth),
    },
    placements,
  };
}

/** Reach of the arm profile a transfer twin carries (UR5e unless it names another). */
export const armReach = (spec: TwinSpec) =>
  armProfiles.find((a) => a.key === (spec.arm ?? "ur5e"))!.reach;

/** World x/z of each drawn deck slot. */
export function siteCentres(spec: TwinSpec, p: Placement) {
  return (spec.sites ?? []).map((site) => {
    const [rx, rz] = rotate(p.yaw, site.x, site.z);
    return { key: site.key, at: [p.x + rx, p.z + rz] as Point };
  });
}
