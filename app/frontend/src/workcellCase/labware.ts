// Labware built from Opentrons labware definitions: wells, depths and footprints come from the JSON.
// Origin is the labware's front-left-bottom; metres; Z up.
import * as THREE from "three";
import type { LabwareDef, Vec3, Well } from "./cell";

const MM = 0.001;
const shared: Record<string, THREE.Material> = {};
function mat<T extends THREE.Material>(key: string, make: () => T): T {
  return (shared[key] ??= make()) as T;
}
const M = {
  rack: () =>
    mat(
      "rack",
      () => new THREE.MeshStandardMaterial({ color: 0xd9dde2, roughness: 0.6 }),
    ),
  dark: () =>
    mat(
      "dark",
      () =>
        new THREE.MeshStandardMaterial({ color: 0x3a3f45, roughness: 0.55 }),
    ),
  poly: () =>
    mat(
      "poly",
      () =>
        new THREE.MeshPhysicalMaterial({
          color: 0xf4f6f8,
          roughness: 0.35,
          transparent: true,
          opacity: 0.38,
          depthWrite: false,
          side: THREE.DoubleSide,
        }),
    ),
  tip: () =>
    mat(
      "tip",
      () =>
        new THREE.MeshStandardMaterial({
          color: 0xf2f4f5,
          roughness: 0.4,
          transparent: true,
          opacity: 0.92,
        }),
    ),
  label: () =>
    mat(
      "label",
      () => new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.8 }),
    ),
};
function box(
  w: number,
  d: number,
  h: number,
  material: THREE.Material,
  x: number,
  y: number,
  z: number,
) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, d, h), material);
  m.position.set(x, y, z);
  return m;
}
const cylZ = (rt: number, rb: number, h: number, seg = 20) =>
  new THREE.CylinderGeometry(rt, rb, h, seg).rotateX(Math.PI / 2);

/** Liquid columns: one mesh per well, scaled to the current volume. */
export class Liquids {
  private cols = new Map<
    string,
    { mesh: THREE.Mesh; area: number; depth: number }
  >();
  add(key: string, well: Well, group: THREE.Object3D, shape: "rect" | "circ") {
    const material = new THREE.MeshStandardMaterial({
      color: 0x4a90c2,
      roughness: 0.25,
      transparent: true,
      opacity: 0.88,
    });
    let geo: THREE.BufferGeometry, area: number;
    if (shape === "rect") {
      geo = new THREE.BoxGeometry(
        well.xDimension! * MM * 0.94,
        well.yDimension! * MM * 0.94,
        1,
      );
      area = well.xDimension! * well.yDimension! * 0.94 * 0.94;
    } else {
      const r = ((well.diameter! * MM) / 2) * 0.86;
      geo = cylZ(r, r * 0.9, 1, 18);
      area = Math.PI * (well.diameter! * 0.43) ** 2;
    }
    geo.translate(0, 0, 0.5);
    const mesh = new THREE.Mesh(geo, material);
    mesh.position.set(well.x * MM, well.y * MM, well.z * MM + 0.0006);
    mesh.scale.z = 1e-5;
    mesh.visible = false;
    mesh.renderOrder = 2;
    group.add(mesh);
    this.cols.set(key, { mesh, area, depth: well.depth * MM });
  }
  set(key: string, volUl: number, rgb: Vec3) {
    const c = this.cols.get(key);
    if (!c) return;
    const h = Math.min(c.depth * 0.96, (volUl / c.area) * 1e-3); // µL / mm² = mm
    c.mesh.visible = volUl > 0.5;
    c.mesh.scale.z = Math.max(1e-5, h);
    (c.mesh.material as THREE.MeshStandardMaterial).color.setRGB(
      rgb[0],
      rgb[1],
      rgb[2],
    );
  }
}

export type TipRack = THREE.Group & {
  hideTip(name: string): void;
  resetTips(): void;
};
/** Tip rack with instanced tip collars so each tip can be removed. */
export function tipRack(def: LabwareDef): TipRack {
  const g = new THREE.Group() as TipRack;
  const { xDimension: X, yDimension: Y, zDimension: Z } = def.dims;
  g.add(
    box(
      X * MM,
      Y * MM,
      (Z - 6) * MM,
      M.rack(),
      (X * MM) / 2,
      (Y * MM) / 2,
      ((Z - 6) * MM) / 2,
    ),
  );
  g.add(
    box(
      X * MM * 0.97,
      Y * MM * 0.95,
      2.2 * MM,
      M.rack(),
      (X * MM) / 2,
      (Y * MM) / 2,
      (Z - 1.1) * MM,
    ),
  );
  const names = def.ordering.flat(),
    r = (def.wells[names[0]].diameter! * MM) / 2;
  const tips = new THREE.InstancedMesh(
    cylZ(r * 1.18, r * 1.05, 8 * MM, 16),
    M.tip(),
    names.length,
  );
  const m4 = new THREE.Matrix4();
  const reset = () => {
    names.forEach((n, i) => {
      const w = def.wells[n];
      m4.makeTranslation(w.x * MM, w.y * MM, (Z + 2.5) * MM);
      tips.setMatrixAt(i, m4);
    });
    tips.instanceMatrix.needsUpdate = true;
  };
  reset();
  g.add(tips);
  g.resetTips = reset;
  g.hideTip = (name) => {
    m4.makeScale(0, 0, 0);
    tips.setMatrixAt(names.indexOf(name), m4);
    tips.instanceMatrix.needsUpdate = true;
  };
  return g;
}

/** Open-top reservoir with trough dividers. */
export function reservoir(def: LabwareDef, liquids: Liquids, prefix: string) {
  const g = new THREE.Group();
  const { xDimension: X, yDimension: Y, zDimension: Z } = def.dims;
  const t = 1.6;
  g.add(
    box(X * MM, Y * MM, 4 * MM, M.rack(), (X * MM) / 2, (Y * MM) / 2, 2 * MM),
  );
  g.add(
    box(
      X * MM,
      t * MM,
      Z * MM,
      M.rack(),
      (X * MM) / 2,
      (t * MM) / 2,
      (Z * MM) / 2,
    ),
  );
  g.add(
    box(
      X * MM,
      t * MM,
      Z * MM,
      M.rack(),
      (X * MM) / 2,
      (Y - t / 2) * MM,
      (Z * MM) / 2,
    ),
  );
  g.add(
    box(
      t * MM,
      Y * MM,
      Z * MM,
      M.rack(),
      (t * MM) / 2,
      (Y * MM) / 2,
      (Z * MM) / 2,
    ),
  );
  g.add(
    box(
      t * MM,
      Y * MM,
      Z * MM,
      M.rack(),
      (X - t / 2) * MM,
      (Y * MM) / 2,
      (Z * MM) / 2,
    ),
  );
  const names = def.ordering.flat();
  names.forEach((n, i) => {
    const w = def.wells[n];
    if (i < names.length - 1) {
      const nx = def.wells[names[i + 1]].x;
      g.add(
        box(
          0.8 * MM,
          (w.yDimension! + 4) * MM,
          w.depth * MM,
          M.poly(),
          ((w.x + nx) / 2) * MM,
          w.y * MM,
          (w.z + w.depth / 2) * MM,
        ),
      );
    }
    liquids.add(`${prefix}:${n}`, w, g, "rect");
  });
  return g;
}

/** Tube rack with tubes and caps in the listed wells. */
export function tubeRack(
  def: LabwareDef,
  liquids: Liquids,
  prefix: string,
  o: { tubes: string[]; cap: number; screw: boolean },
) {
  const g = new THREE.Group();
  const { xDimension: X, yDimension: Y } = def.dims;
  const names = def.ordering.flat(),
    w0 = def.wells[names[0]];
  const topZ = w0.z + w0.depth - 6;
  g.add(
    box(X * MM, Y * MM, 3 * MM, M.rack(), (X * MM) / 2, (Y * MM) / 2, 1.5 * MM),
  );
  g.add(
    box(
      X * MM,
      Y * MM,
      2.4 * MM,
      M.rack(),
      (X * MM) / 2,
      (Y * MM) / 2,
      topZ * MM,
    ),
  );
  g.add(
    box(
      X * MM * 0.96,
      Y * MM * 0.92,
      2 * MM,
      M.rack(),
      (X * MM) / 2,
      (Y * MM) / 2,
      (w0.z - 6) * MM,
    ),
  );
  for (const sx of [0, 1])
    for (const sy of [0, 1])
      g.add(
        box(
          4 * MM,
          4 * MM,
          topZ * MM,
          M.dark(),
          (sx ? X - 2 : 2) * MM,
          (sy ? Y - 2 : 2) * MM,
          (topZ * MM) / 2,
        ),
      );
  g.add(
    box(
      X * MM * 0.62,
      0.6 * MM,
      14 * MM,
      M.label(),
      (X * MM) / 2,
      -0.3 * MM,
      (topZ - 12) * MM,
    ),
  );
  const rim = new THREE.InstancedMesh(
    new THREE.TorusGeometry((w0.diameter! / 2 + 0.8) * MM, 0.55 * MM, 6, 20),
    M.dark(),
    names.length,
  );
  const m4 = new THREE.Matrix4();
  names.forEach((n, i) => {
    const w = def.wells[n];
    m4.makeTranslation(w.x * MM, w.y * MM, (topZ + 1.3) * MM);
    rim.setMatrixAt(i, m4);
  });
  g.add(rim);
  const capMat = new THREE.MeshStandardMaterial({
    color: o.cap,
    roughness: 0.5,
  });
  for (const n of o.tubes) {
    const w = def.wells[n],
      r = (w.diameter! * MM) / 2,
      h = (w.depth + 2) * MM;
    const tube = new THREE.Mesh(cylZ(r + 0.6 * MM, r * 0.7, h, 22), M.poly());
    tube.position.set(w.x * MM, w.y * MM, (w.z - 1) * MM + h / 2);
    g.add(tube);
    const ch = (o.screw ? 9 : 4) * MM,
      cr = r + (o.screw ? 1.6 : 1.2) * MM;
    const c = new THREE.Mesh(cylZ(cr, cr, ch, 22), capMat);
    c.position.set(w.x * MM, w.y * MM, (w.z + w.depth + 1) * MM + ch / 2);
    g.add(c);
    if (!o.screw)
      g.add(
        box(
          3 * MM,
          5 * MM,
          1.2 * MM,
          capMat,
          w.x * MM,
          (w.y - w.diameter! / 2 - 2) * MM,
          (w.z + w.depth) * MM,
        ),
      );
    liquids.add(`${prefix}:${n}`, w, g, "circ");
  }
  return g;
}
