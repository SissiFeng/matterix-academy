// Synthesis workcell layout in the UR5e base frame (metres, Z up). Pure math, no rendering.
import {
  DEG,
  downPose,
  fk,
  frames,
  ik,
  withinLimits,
  type Mat4,
  type Waypoint,
} from "./kin";

export type Vec3 = [number, number, number];
export type Frame = "flex" | "ot2";
export type Box = {
  owner: string;
  part: string;
  min: Vec3;
  max: Vec3;
  skipNearBase?: boolean;
};
export type Deck = {
  corner: number[];
  cutouts: Record<string, number[]>;
  areas: Record<string, { off: number[]; box: Record<string, number> }>;
};
export type Decks = Record<Frame, Deck>;
export type Well = {
  x: number;
  y: number;
  z: number;
  depth: number;
  shape: string;
  diameter?: number;
  xDimension?: number;
  yDimension?: number;
  totalLiquidVolume: number;
};
export type LabwareDef = {
  displayName: string;
  dims: { xDimension: number; yDimension: number; zDimension: number };
  ordering: string[][];
  wells: Record<string, Well>;
  tipLength?: number;
  tipOverlap?: number;
};
export type LabwareSet = Record<string, LabwareDef>;
export type Station = {
  id: "flex" | "balance" | "ot2";
  label: string;
  x: number;
  y: number;
  base: number;
  front: [number, number] | null;
};

// Robotiq 2F-140 on the UR flange: coupling 13.9 mm + pad centre ~190 mm when closed on 85.5 mm.
export const TCP = 0.204;
export const RACK = { L: 0.12775, W: 0.0855, H: 0.08535, grip: 0.016 };
// Opening only 18 mm wider than the rack keeps the pads out of the neighbouring slots.
export const GAP_OPEN = RACK.W + 0.018;
export const GAP_CLOSED = RACK.W + 0.0015;
export const APPROACH = 0.12;
// Inside the OT-2 the wrist has little headroom: approach just high enough for the pads
// (13.5 mm below the TCP) to clear the 85 mm vials by 8 mm.
export const OT2_APPROACH = RACK.H - RACK.grip + 0.0135 + 0.008;
export const HOME = [60, -90, 90, -90, -90, 0];

// Deck layout by Opentrons slot name. The OT-2 slot behind slot 2 (slot 5) stays empty:
// the gripper's pads open front-to-back there.
export const LAYOUT = {
  flex: {
    tips: { slot: "A1", def: "opentrons_flex_96_tiprack_1000ul" },
    solvent: { slot: "B1", def: "nest_12_reservoir_15ml" },
    stocks: { slot: "B2", def: "opentrons_24_tuberack_nest_1.5ml_snapcap" },
    rack: { slot: "D2", def: "opentrons_24_tuberack_nest_2ml_screwcap" },
  },
  ot2: {
    tips: { slot: "1", def: "opentrons_96_tiprack_300ul" },
    reagents: { slot: "4", def: "nest_12_reservoir_15ml" },
    mixes: { slot: "3", def: "opentrons_24_tuberack_nest_1.5ml_snapcap" },
    rack: { slot: "2", def: "opentrons_24_tuberack_nest_2ml_screwcap" },
  },
} as const;

// Instrument frames follow the Opentrons deck definitions: deck mm + cornerOffsetFromOrigin, Z up,
// machine front toward local -Y. Each frame is placed on the bench by yaw + translation.
export const FRAMES: Record<Frame, { yaw: number; t: Vec3; deckZ: number }> = {
  flex: { yaw: -Math.PI / 2, t: [0.531, 0.05, 0.153], deckZ: 0.153 },
  ot2: { yaw: Math.PI / 2, t: [-0.455, -0.1965, 0.1], deckZ: 0.1 },
};
export const ENVELOPE: Record<
  Frame,
  { x: number[]; y: number[]; z: number[] }
> = {
  flex: { x: [-0.383, 0.484], y: [-0.191, 0.483], z: [-0.153, 0.648] },
  ot2: { x: [-0.12, 0.513], y: [-0.115, 0.455], z: [-0.1, 0.56] },
};
export const BALANCE = {
  centre: [0.0, -0.47] as [number, number],
  size: [0.21, 0.3, 0.088] as Vec3,
  pan: [0.0, -0.445, 0.098] as Vec3,
  panSize: 0.17,
};

export function toRobot(frame: Frame, p: number[]): Vec3 {
  const f = FRAMES[frame],
    c = Math.cos(f.yaw),
    s = Math.sin(f.yaw);
  return [
    c * p[0] - s * p[1] + f.t[0],
    s * p[0] + c * p[1] + f.t[1],
    p[2] + f.t[2],
  ];
}
export function slotOrigin(decks: Decks, frame: Frame, slot: string): Vec3 {
  const d = decks[frame],
    p = d.cutouts[`cutout${slot}`];
  return [
    (p[0] + d.corner[0]) / 1000,
    (p[1] + d.corner[1]) / 1000,
    (p[2] + d.corner[2]) / 1000,
  ];
}

export function stations(decks: Decks): Record<Station["id"], Station> {
  const centre = (frame: Frame, slot: string) => {
    const o = slotOrigin(decks, frame, slot);
    return toRobot(frame, [o[0] + RACK.L / 2, o[1] + RACK.W / 2, 0]);
  };
  const flex = centre("flex", LAYOUT.flex.rack.slot),
    ot2 = centre("ot2", LAYOUT.ot2.rack.slot);
  return {
    flex: {
      id: "flex",
      label: "Flex D2",
      x: flex[0],
      y: flex[1],
      base: flex[2],
      front: [0.215, flex[1]],
    },
    balance: {
      id: "balance",
      label: "Balance pan",
      x: BALANCE.pan[0],
      y: BALANCE.pan[1],
      base: BALANCE.pan[2],
      front: null,
    },
    ot2: {
      id: "ot2",
      label: "OT-2 slot 2",
      x: ot2[0],
      y: ot2[1],
      base: ot2[2],
      front: [-0.215, ot2[1]],
    },
  };
}

function frameBox(
  owner: string,
  part: string,
  frame: Frame,
  lo: number[],
  hi: number[],
): Box {
  const corners: Vec3[] = [];
  for (const x of [lo[0], hi[0]])
    for (const y of [lo[1], hi[1]]) corners.push(toRobot(frame, [x, y, 0]));
  const xs = corners.map((c) => c[0]),
    ys = corners.map((c) => c[1]),
    dz = FRAMES[frame].t[2];
  return {
    owner,
    part,
    min: [Math.min(...xs), Math.min(...ys), lo[2] + dz],
    max: [Math.max(...xs), Math.max(...ys), hi[2] + dz],
  };
}

/** Walls, roofs and deck plinths (fronts stay open), the Flex touchscreen and the balance housing. */
export function keepouts(): Box[] {
  const boxes: Box[] = [];
  for (const [frame, name] of [
    ["flex", "Flex"],
    ["ot2", "OT-2"],
  ] as const) {
    const e = ENVELOPE[frame],
      w = 0.035;
    boxes.push(
      frameBox(
        name,
        "back wall",
        frame,
        [e.x[0], e.y[1] - w, e.z[0]],
        [e.x[1], e.y[1], e.z[1]],
      ),
    );
    boxes.push(
      frameBox(
        name,
        "left wall",
        frame,
        [e.x[0], e.y[0], e.z[0]],
        [e.x[0] + w, e.y[1], e.z[1]],
      ),
    );
    boxes.push(
      frameBox(
        name,
        "right wall",
        frame,
        [e.x[1] - w, e.y[0], e.z[0]],
        [e.x[1], e.y[1], e.z[1]],
      ),
    );
    boxes.push(
      frameBox(
        name,
        "roof",
        frame,
        [e.x[0], e.y[0], e.z[1] - 0.06],
        [e.x[1], e.y[1], e.z[1]],
      ),
    );
    boxes.push(
      frameBox(
        name,
        "deck",
        frame,
        [e.x[0], e.y[0], e.z[0]],
        [e.x[1], e.y[1], 0],
      ),
    );
  }
  boxes.push(
    frameBox(
      "OT-2",
      "front header",
      "ot2",
      [ENVELOPE.ot2.x[0], ENVELOPE.ot2.y[0], 0.52],
      [ENVELOPE.ot2.x[1], ENVELOPE.ot2.y[0] + 0.03, 0.56],
    ),
  );
  boxes.push(
    frameBox(
      "Flex",
      "front header",
      "flex",
      [ENVELOPE.flex.x[0], ENVELOPE.flex.y[0], 0.6],
      [ENVELOPE.flex.x[1], ENVELOPE.flex.y[0] + 0.03, 0.648],
    ),
  );
  boxes.push(
    frameBox(
      "Flex",
      "touchscreen",
      "flex",
      [0.43, -0.27, 0.26],
      [0.53, -0.19, 0.42],
    ),
  );
  const [bx, by] = BALANCE.centre,
    [sx, sy, sz] = BALANCE.size;
  boxes.push({
    owner: "Balance",
    part: "housing",
    min: [bx - sx / 2, by - sy / 2, 0],
    max: [bx + sx / 2, by + sy / 2, sz],
  });
  boxes.push({
    owner: "Bench",
    part: "surface",
    min: [-1.4, -1.0, -0.05],
    max: [1.4, 1.0, 0],
    skipNearBase: true,
  });
  return boxes;
}

/** Fixed labware on both decks (the moving sample rack is excluded) plus the trash fixtures. */
export function labwareBoxes(decks: Decks, lw: LabwareSet): Box[] {
  const boxes: Box[] = [];
  for (const frame of ["flex", "ot2"] as const)
    for (const [key, item] of Object.entries(LAYOUT[frame])) {
      if (key === "rack") continue;
      const o = slotOrigin(decks, frame, item.slot),
        d = lw[item.def].dims;
      boxes.push(
        frameBox(
          frame === "flex" ? "Flex" : "OT-2",
          `${item.slot} ${lw[item.def].displayName}`,
          frame,
          [o[0], o[1], o[2]],
          [
            o[0] + d.xDimension / 1000,
            o[1] + d.yDimension / 1000,
            d.zDimension / 1000 + 0.012,
          ],
        ),
      );
    }
  const trash = (frame: Frame, cut: string, area: string, owner: string) => {
    const d = decks[frame],
      a = d.areas[area],
      c = d.cutouts[cut];
    const x = (c[0] + a.off[0] + d.corner[0]) / 1000,
      y = (c[1] + a.off[1] + d.corner[1]) / 1000;
    boxes.push(
      frameBox(
        owner,
        "trash",
        frame,
        [x, y, 0],
        [
          x + a.box.xDimension / 1000,
          y + a.box.yDimension / 1000,
          a.box.zDimension / 1000,
        ],
      ),
    );
  };
  trash("flex", "cutoutA3", "movableTrashA3", "Flex");
  trash("ot2", "cutout12", "fixedTrash", "OT-2");
  return boxes;
}

const add3 = (a: number[], b: number[], s = 1): Vec3 => [
  a[0] + b[0] * s,
  a[1] + b[1] * s,
  a[2] + b[2] * s,
];
const col = (m: Mat4, c: number) => [m[0][c], m[1][c], m[2][c]];
export function capsules(q: number[]) {
  const F = frames(q, TCP);
  const o = (i: number) => col(F[i], 3),
    z = (i: number) => col(F[i], 2);
  return [
    {
      name: "Upper arm",
      a: add3(o(1), z(1), 0.138),
      b: add3(o(2), z(2), 0.138),
      r: 0.054,
    },
    { name: "Elbow", a: o(2), b: add3(o(2), z(2), 0.138), r: 0.058 },
    { name: "Forearm", a: o(2), b: o(3), r: 0.042 },
    { name: "Wrist 1", a: o(3), b: o(4), r: 0.044 },
    { name: "Wrist 2", a: o(4), b: o(5), r: 0.044 },
    { name: "Wrist 3", a: o(5), b: o(6), r: 0.044 },
    { name: "Gripper", a: o(6), b: add3(o(6), z(6), 0.15), r: 0.045 },
  ];
}
export type Hit = { link: string; owner: string; part: string };
const inside = (p: number[], b: Box, r: number) =>
  p[0] > b.min[0] - r &&
  p[0] < b.max[0] + r &&
  p[1] > b.min[1] - r &&
  p[1] < b.max[1] + r &&
  p[2] > b.min[2] - r &&
  p[2] < b.max[2] + r;

let BOXES: Box[] | null = null;
/** Arm link capsules against the enclosure keep-outs. */
export function clearance(q: number[]): Hit[] {
  BOXES ??= keepouts();
  const hits: Hit[] = [];
  for (const c of capsules(q)) {
    let hit: Hit | null = null;
    for (let k = 0; k <= 8 && !hit; k++) {
      const p = add3(
        c.a,
        [c.b[0] - c.a[0], c.b[1] - c.a[1], c.b[2] - c.a[2]],
        k / 8,
      );
      for (const b of BOXES) {
        if (b.skipNearBase && Math.hypot(p[0], p[1]) < 0.2) continue;
        if (inside(p, b, c.r)) {
          hit = { link: c.name, owner: b.owner, part: b.part };
          break;
        }
      }
    }
    if (hit) hits.push(hit);
  }
  return hits;
}

function grid(lo: number[], hi: number[], n = 3): number[][] {
  const pts: number[][] = [];
  for (let i = 0; i < n; i++)
    for (let j = 0; j < n; j++)
      for (let k = 0; k < n; k++)
        pts.push(
          [0, 1, 2].map(
            (a, x) => lo[a] + ((hi[a] - lo[a]) * [i, j, k][x]) / (n - 1),
          ),
        );
  return pts;
}
const apply = (T: Mat4, p: number[]) =>
  [0, 1, 2].map(
    (i) => T[i][0] * p[0] + T[i][1] * p[1] + T[i][2] * p[2] + T[i][3],
  );
// Tool-frame volumes (tool Z points down): finger pads and fingers, and a carried rack.
const pads = (gap: number) => [
  grid([gap / 2, -0.0325, -0.06], [gap / 2 + 0.012, 0.0325, 0.0135]),
  grid([-gap / 2 - 0.012, -0.0325, -0.06], [-gap / 2, 0.0325, 0.0135]),
];
const carried = grid(
  [-RACK.W / 2, -RACK.L / 2, RACK.grip - RACK.H],
  [RACK.W / 2, RACK.L / 2, RACK.grip],
  4,
);

/**
 * Fingers and the carried rack against labware, decks and enclosures. A 2 mm allowance lets the
 * rack rest on a deck or pan and the pads clear a rack they hold.
 */
export function toolClearance(
  q: number[],
  gap: number,
  holding: boolean,
  labware: Box[],
): Hit[] {
  BOXES ??= keepouts();
  const T = fk(q, TCP),
    hits: Hit[] = [];
  const check = (name: string, pts: number[][], boxes: Box[]) => {
    for (const p of pts) {
      const w = apply(T, p);
      for (const b of boxes) {
        if (b.skipNearBase) continue;
        if (inside(w, b, -0.002)) {
          hits.push({ link: name, owner: b.owner, part: b.part });
          return;
        }
      }
    }
  };
  for (const side of pads(gap)) check("Finger", side, [...labware, ...BOXES]);
  if (holding) check("Carried rack", carried, [...labware, ...BOXES]);
  return hits;
}

const az = (q: number[]) => {
  const f = fk(q, TCP);
  return Math.atan2(f[1][3], f[0][3]);
};
const wrap = (a: number) => Math.atan2(Math.sin(a), Math.cos(a));
/** Tool-down IK near the seed. Large base turns go through the open front of the cell (−90°). */
export function reach(
  x: number,
  y: number,
  z: number,
  seedDeg: number[],
  yaws = [0, Math.PI],
): number[] | null {
  const seed = seedDeg.map((v) => v * DEG);
  const a0 = az(seed),
    a1 = Math.atan2(y, x);
  let d = wrap(a1 - a0);
  if (Math.abs(d) > 2.4) {
    const cands = [d, d - 2 * Math.PI * Math.sign(d)];
    d = cands.sort(
      (p, r) =>
        Math.abs(wrap(a0 + p / 2 + Math.PI / 2)) -
        Math.abs(wrap(a0 + r / 2 + Math.PI / 2)),
    )[0];
  }
  let best: { q: number[]; cost: number } | null = null;
  for (const yaw of yaws)
    for (const s of [[seed[0] + d, ...seed.slice(1)], seed]) {
      const r = ik(downPose(x, y, z, yaw), s, TCP);
      if (!r) continue;
      const cost = Math.max(...r.q.map((v, i) => Math.abs(v - seed[i])));
      if (!best || cost < best.cost) best = { q: r.q, cost };
    }
  return best ? best.q.map((v) => +(v / DEG).toFixed(2)) : null;
}
export { withinLimits };

/** The default transfer: Flex D2 → balance (weigh) → OT-2 slot 2. */
export function generateTransfer(
  st: Record<Station["id"], Station>,
): Waypoint[] {
  const rows: Waypoint[] = [];
  let seed = HOME;
  // The rack keeps its world orientation while carried. The instruments face each other, so the
  // wrist turns 180° on the way and the rack lands in OT-2 slot 2 with A1 at the back-left.
  let yaws = [0];
  const push = (
    name: string,
    x: number,
    y: number,
    z: number,
    extra: Partial<Waypoint> = {},
  ) => {
    const deg = reach(x, y, z, seed, yaws);
    if (!deg) throw new Error(`${name}: no nearby IK solution`);
    rows.push({ name, degrees: deg, hold: 0, grip: null, ...extra });
    seed = deg;
  };
  // The pads open along the line between the instruments, so the gripper must come down onto a
  // rack from above: sliding in or out at deck height would drag a finger through the rack.
  const g = (s: Station) => s.base + RACK.grip,
    up = (s: Station) => g(s) + (s.id === "ot2" ? OT2_APPROACH : APPROACH);
  const { flex, balance, ot2 } = st;
  // Joint-space interpolation drifts ~13 mm sideways over a 120 mm vertical move; the pads have
  // 9 mm to spare beside the rack. A halfway point keeps the drift near 3 mm where it matters.
  const vertical = (
    name: string,
    s0: Station,
    from: number,
    to: number,
    extra: Partial<Waypoint> = {},
  ) => {
    push(`${name} · halfway`, s0.x, s0.y, (from + to) / 2);
    push(name, s0.x, s0.y, to, extra);
  };
  push("Front of Flex", flex.front![0], flex.front![1], up(flex));
  push("Above Flex D2", flex.x, flex.y, up(flex));
  vertical("Grip sample rack", flex, up(flex), g(flex), {
    hold: 1,
    grip: "close",
  });
  push("Lift from Flex", flex.x, flex.y, up(flex));
  push("Back out of Flex", flex.front![0], flex.front![1], up(flex));
  yaws = [0, Math.PI];
  push("Above balance", balance.x, balance.y, up(balance));
  push("Set rack on pan", balance.x, balance.y, g(balance), {
    hold: 1,
    grip: "open",
  });
  push("Clear pan · weigh", balance.x, balance.y, up(balance), { hold: 6 });
  push("Regrip on pan", balance.x, balance.y, g(balance), {
    hold: 1,
    grip: "close",
  });
  push("Lift from balance", balance.x, balance.y, up(balance));
  yaws = [Math.PI];
  push("Front of OT-2", ot2.front![0], ot2.front![1], up(ot2));
  push("Above OT-2 slot 2", ot2.x, ot2.y, up(ot2));
  vertical("Place rack in OT-2", ot2, up(ot2), g(ot2), {
    hold: 1,
    grip: "open",
  });
  vertical("Lift clear of rack", ot2, g(ot2), up(ot2));
  push("Back out of OT-2", ot2.front![0], ot2.front![1], up(ot2));
  rows.push({
    name: "Return home",
    degrees: HOME.slice(),
    hold: 0,
    grip: null,
  });
  return rows;
}
