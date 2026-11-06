import type { Layout, Placement, Twin, TwinSpec } from "./instrumentTypes";

/** Mirrors workcell_layout.py; the server's check is authoritative. */
export const ARM_RADII = [0.075, 0.065, 0.055, 0.048, 0.048, 0.048, 0.06];
export const REACH = 0.85;
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

/** Mirrors workcell_layout.mount: the arm base frame (Z up) on top of its pedestal, as a Y-up world matrix. */
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

/** Midpoint of the front face, where a front access point sits. */
export function frontFace(spec: TwinSpec, p: Placement): Point {
  const { x0, x1, z1 } = footprint(spec);
  const [rx, rz] = rotate(p.yaw, (x0 + x1) / 2, z1);
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

/** A starting layout: arms in the middle, stations on an arc in front of them. */
export function defaultLayout(twins: Twin[]): Layout {
  const arms = twins.filter(isArm);
  const stations = twins.filter((t) => !isArm(t));
  const placements: Placement[] = arms.map((t, i) => ({
    twin_id: t.id,
    x: Number(((i - (arms.length - 1) / 2) * 0.9).toFixed(2)),
    z: 0,
    yaw: 0,
    access: "top",
  }));
  stations.forEach((t, i) => {
    const angle =
      stations.length === 1
        ? Math.PI / 2
        : Math.PI * 0.05 + (Math.PI * 0.9 * i) / (stations.length - 1);
    const radius = 0.55;
    placements.push({
      twin_id: t.id,
      x: Number((-Math.cos(angle) * radius).toFixed(2)),
      z: Number((Math.sin(angle) * radius * 0.75 + 0.05).toFixed(2)),
      yaw: 0,
      access: "top",
    });
  });
  return { bench: { width: 2.4, depth: 1.6 }, placements };
}
