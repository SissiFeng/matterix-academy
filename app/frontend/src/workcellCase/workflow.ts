// Liquid-handling timeline for the case: Flex sample prep, OT-2 reagent prep and synthesis.
// A synthetic teaching model: volumes, timings, densities and masses are illustrative.
import {
  LAYOUT,
  slotOrigin,
  type Decks,
  type Frame,
  type LabwareSet,
  type Vec3,
} from "./cell";

const MM = 0.001;
export type LiquidKey =
  "solvent" | "s1" | "s2" | "s3" | "s4" | "s5" | "s6" | "reagent" | "catalyst";
export type Comp = Partial<Record<LiquidKey, number>>;
export const LIQUIDS: Record<
  LiquidKey,
  { name: string; rgb: Vec3; density: number }
> = {
  solvent: { name: "Solvent (DMF)", rgb: [0.78, 0.86, 0.96], density: 0.944 },
  s1: { name: "Substrate 1", rgb: [0.96, 0.78, 0.3], density: 1.05 },
  s2: { name: "Substrate 2", rgb: [0.94, 0.62, 0.24], density: 1.05 },
  s3: { name: "Substrate 3", rgb: [0.9, 0.46, 0.22], density: 1.05 },
  s4: { name: "Substrate 4", rgb: [0.82, 0.34, 0.3], density: 1.05 },
  s5: { name: "Substrate 5", rgb: [0.7, 0.28, 0.4], density: 1.05 },
  s6: { name: "Substrate 6", rgb: [0.56, 0.26, 0.48], density: 1.05 },
  reagent: { name: "Reagent R", rgb: [0.36, 0.72, 0.52], density: 1.1 },
  catalyst: { name: "Catalyst C", rgb: [0.42, 0.34, 0.8], density: 0.98 },
};
export const RACK_TARE_G = 61.842; // empty 24-position rack with six capped 2 mL vials (illustrative)
export const VIALS = ["A1", "A2", "A3", "A4", "A5", "A6"];

export type Dev = "flex" | "ot2";
export type LiquidEvent =
  | { type: "tipPick"; t: number; dev: Dev; rack: string; well: string }
  | { type: "tipDrop"; t: number; dev: Dev }
  | { type: "mix"; t: number; dev: Dev; well: string; n: number }
  | {
      type: "move";
      t0: number;
      t1: number;
      dev: Dev;
      from: string;
      to: string;
      vol: number;
      all?: boolean;
    };
export type GantrySeg = { t0: number; t1: number; p0: Vec3; p1: Vec3 };
export type Op = { label: string; t0: number; t1: number };
export const eventTime = (e: LiquidEvent) => ("t" in e ? e.t : e.t0);

export function initialWells(): Map<string, Comp> {
  const w = new Map<string, Comp>();
  w.set("flex:solvent:A1", { solvent: 12000 });
  VIALS.forEach((v, i) =>
    w.set(`flex:stocks:${v}`, { [`s${i + 1}`]: 1200 } as Comp),
  );
  VIALS.forEach((v) => w.set(`rack:${v}`, {}));
  w.set("ot2:reagents:A1", { reagent: 12000 });
  w.set("ot2:reagents:A2", { catalyst: 8000 });
  VIALS.forEach((v) => w.set(`ot2:mixes:${v}`, {}));
  return w;
}
const entries = (c: Comp) => Object.entries(c) as [LiquidKey, number][];
export const total = (c: Comp) => entries(c).reduce((a, [, v]) => a + v, 0);
export function colour(c: Comp): Vec3 {
  const v = total(c);
  if (v <= 0) return [0.5, 0.5, 0.5];
  const out: Vec3 = [0, 0, 0];
  for (const [k, x] of entries(c))
    LIQUIDS[k].rgb.forEach((ch, i) => (out[i] += (ch * x) / v));
  return out;
}
export const massG = (c: Comp) =>
  entries(c).reduce((m, [k, v]) => m + v * 1e-3 * LIQUIDS[k].density, 0);

const SPEED = { flex: { xy: 0.3, z: 0.12 }, ot2: { xy: 0.26, z: 0.1 } };
const T_ASP = 1.4,
  T_DISP = 1.2,
  T_PICK = 1.3,
  T_DROP = 1.0,
  T_MIX = 0.7;
type WellPos = [number, number, number, number]; // x, y, bottom z, top z

// One liquid handler's motion; N is the nozzle point in the instrument frame.
function handler(
  dev: Dev,
  o: { reach: number; safeZ: number; park: Vec3; trash: Vec3 },
) {
  const segs: GantrySeg[] = [],
    events: LiquidEvent[] = [],
    ops: Op[] = [];
  let t = 0,
    N: Vec3 = [...o.park];
  const reach = o.reach,
    safeZ = o.safeZ;
  const ease = (a: Vec3, b: Vec3, dur: number) => {
    if (dur > 0) segs.push({ t0: t, t1: t + dur, p0: [...a], p1: [...b] });
    t += dur;
  };
  const go = (P: Vec3) => {
    const sp = SPEED[dev];
    if (N[2] < safeZ - 1e-6) {
      const lift: Vec3 = [N[0], N[1], safeZ];
      ease(N, lift, Math.max(0.2, (safeZ - N[2]) / sp.z));
      N = lift;
    }
    const flat: Vec3 = [P[0], P[1], safeZ];
    const d = Math.hypot(flat[0] - N[0], flat[1] - N[1]);
    if (d > 1e-4) {
      ease(N, flat, Math.max(0.3, d / sp.xy));
      N = flat;
    }
    if (Math.abs(P[2] - N[2]) > 1e-5) {
      ease(N, P, Math.max(0.2, Math.abs(N[2] - P[2]) / sp.z));
      N = [...P];
    }
  };
  const hold = (dur: number) => {
    segs.push({ t0: t, t1: t + dur, p0: [...N], p1: [...N] });
    t += dur;
  };
  const api = {
    get t() {
      return t;
    },
    op(label: string, fn: () => void) {
      const a = t;
      fn();
      ops.push({ label, t0: a, t1: t });
    },
    pick(rack: string, well: string, topZ: number, xy: WellPos) {
      go([xy[0], xy[1], topZ + 0.02]);
      go([xy[0], xy[1], topZ - 0.008]);
      events.push({ t: t + T_PICK * 0.5, type: "tipPick", dev, rack, well });
      hold(T_PICK);
      go([xy[0], xy[1], safeZ]);
    },
    aspirate(key: string, vol: number, pos: WellPos, depth = 0.003) {
      go([pos[0], pos[1], pos[3] + reach + 0.008]);
      go([pos[0], pos[1], pos[2] + depth + reach]);
      events.push({
        t0: t,
        t1: t + T_ASP,
        type: "move",
        dev,
        from: key,
        to: `tip:${dev}`,
        vol,
      });
      hold(T_ASP);
      go([pos[0], pos[1], pos[3] + reach + 0.008]);
    },
    dispense(key: string, vol: number, pos: WellPos, height = 0.012) {
      go([pos[0], pos[1], pos[3] + reach + 0.008]);
      go([pos[0], pos[1], pos[2] + height + reach]);
      events.push({
        t0: t,
        t1: t + T_DISP,
        type: "move",
        dev,
        from: `tip:${dev}`,
        to: key,
        vol,
        all: true,
      });
      hold(T_DISP);
    },
    mix(key: string, pos: WellPos, n = 3) {
      const lo: Vec3 = [pos[0], pos[1], pos[2] + 0.004 + reach],
        hi: Vec3 = [pos[0], pos[1], pos[2] + 0.014 + reach];
      go(lo);
      events.push({ t, type: "mix", dev, well: key, n });
      for (let i = 0; i < n; i++) {
        ease(N, hi, T_MIX / 2);
        N = hi;
        ease(N, lo, T_MIX / 2);
        N = lo;
      }
      go([pos[0], pos[1], pos[3] + reach + 0.008]);
    },
    drop() {
      go([o.trash[0], o.trash[1], o.trash[2] + reach + 0.02]);
      events.push({ t: t + T_DROP * 0.4, type: "tipDrop", dev });
      hold(T_DROP);
    },
    park() {
      go(o.park);
    },
    wait(until: number) {
      if (until > t) hold(until - t);
    },
  };
  return { api, segs, events, ops };
}
export type Handler = ReturnType<typeof handler>;

function where(decks: Decks, lw: LabwareSet, frame: Frame, key: string) {
  const L = (LAYOUT[frame] as Record<string, { slot: string; def: string }>)[
    key
  ];
  const o = slotOrigin(decks, frame, L.slot),
    def = lw[L.def];
  return {
    def,
    well(n: string): WellPos {
      const w = def.wells[n];
      return [
        o[0] + w.x * MM,
        o[1] + w.y * MM,
        o[2] + w.z * MM,
        o[2] + (w.z + w.depth) * MM,
      ];
    },
    top(n: string) {
      const w = def.wells[n];
      return o[2] + (w.z + w.depth) * MM;
    },
  };
}

export type HandlerFrame = { reach: number; park: Vec3; trash?: Vec3 };
export function buildPrep(
  decks: Decks,
  lw: LabwareSet,
  frames: { flex: HandlerFrame; ot2: HandlerFrame & { trash: Vec3 } },
) {
  const fd = decks.flex,
    area = fd.areas.movableTrashA3,
    cut = fd.cutouts.cutoutA3;
  const fTrash: Vec3 = [
    (cut[0] + area.off[0] + area.box.xDimension / 2 + fd.corner[0]) * MM,
    (cut[1] + area.off[1] + area.box.yDimension / 2 + fd.corner[1]) * MM,
    area.box.zDimension * MM,
  ];
  const F = handler("flex", {
    reach: frames.flex.reach,
    safeZ: 0.29,
    park: frames.flex.park,
    trash: fTrash,
  });
  const fl = (k: string) => where(decks, lw, "flex", k);
  const ftips = fl("tips"),
    solv = fl("solvent"),
    stocks = fl("stocks"),
    rackF = fl("rack");
  const tipOrder = ftips.def.ordering.flat();
  let ti = 0;
  const nextTip = () => {
    const n = tipOrder[ti++];
    F.api.pick("flex:tips", n, ftips.top(n), ftips.well(n));
  };
  F.api.op("Flex · Dispense 900 µL solvent into six vials", () => {
    nextTip();
    for (const v of VIALS) {
      F.api.aspirate("flex:solvent:A1", 900, solv.well("A1"));
      F.api.dispense(`rack:${v}`, 900, rackF.well(v), 0.03);
    }
    F.api.drop();
  });
  F.api.op("Flex · Add 100 µL substrate stock and mix", () => {
    VIALS.forEach((v) => {
      nextTip();
      F.api.aspirate(`flex:stocks:${v}`, 100, stocks.well(v));
      F.api.dispense(`rack:${v}`, 100, rackF.well(v), 0.02);
      F.api.mix(`rack:${v}`, rackF.well(v));
      F.api.drop();
    });
    F.api.park();
  });
  const O = handler("ot2", {
    reach: frames.ot2.reach,
    safeZ: 0.22,
    park: frames.ot2.park,
    trash: frames.ot2.trash,
  });
  const ol = (k: string) => where(decks, lw, "ot2", k);
  const otips = ol("tips"),
    reag = ol("reagents"),
    mixes = ol("mixes");
  const oOrder = otips.def.ordering.flat();
  let oi = 0;
  const nextOT = () => {
    const n = oOrder[oi++];
    O.api.pick("ot2:tips", n, otips.top(n), otips.well(n));
  };
  O.api.op("OT-2 · Aliquot 250 µL reagent R", () => {
    nextOT();
    for (const v of VIALS) {
      O.api.aspirate("ot2:reagents:A1", 250, reag.well("A1"));
      O.api.dispense(`ot2:mixes:${v}`, 250, mixes.well(v), 0.025);
    }
    O.api.drop();
  });
  O.api.op("OT-2 · Add 50 µL catalyst C", () => {
    nextOT();
    for (const v of VIALS) {
      O.api.aspirate("ot2:reagents:A2", 50, reag.well("A2"));
      O.api.dispense(`ot2:mixes:${v}`, 50, mixes.well(v), 0.03);
    }
    O.api.drop();
    O.api.park();
  });
  return {
    F,
    O,
    nextOT,
    mixes,
    rackOT2: ol("rack"),
    end: Math.max(F.api.t, O.api.t),
  };
}
export type Prep = ReturnType<typeof buildPrep>;
export const SYNTHESIS = "OT-2 · Add 200 µL reagent mix to each vial and mix";

export function addSynthesis(prep: Prep, start: number) {
  const O = prep.O,
    rack = prep.rackOT2;
  O.api.wait(start);
  O.api.op(SYNTHESIS, () => {
    for (const v of VIALS) {
      prep.nextOT();
      O.api.aspirate(`ot2:mixes:${v}`, 200, prep.mixes.well(v));
      O.api.dispense(`rack:${v}`, 200, rack.well(v), 0.03);
      O.api.mix(`rack:${v}`, rack.well(v));
      O.api.drop();
    }
    O.api.park();
  });
  return O.api.t;
}

export type LiquidState = {
  wells: Map<string, Comp>;
  tips: Record<Dev, boolean>;
  tipComp: Record<Dev, Comp>;
  used: Set<string>;
};
export function liquidState(events: LiquidEvent[], T: number): LiquidState {
  const wells = initialWells();
  const tips: Record<Dev, boolean> = { flex: false, ot2: false };
  const tipComp: Record<Dev, Comp> = { flex: {}, ot2: {} };
  const used = new Set<string>();
  const take = (src: Comp, vol: number): Comp => {
    const v = total(src);
    if (v <= 0) return {};
    const f = Math.min(1, vol / v),
      out: Comp = {};
    for (const [k, x] of entries(src)) {
      out[k] = x * f;
      src[k] = x - out[k]!;
      if (src[k]! < 1e-6) delete src[k];
    }
    return out;
  };
  const merge = (dst: Comp, add: Comp) => {
    for (const [k, v] of entries(add)) dst[k] = (dst[k] || 0) + v;
  };
  for (const e of events) {
    if (e.type === "tipPick") {
      if (T >= e.t) {
        used.add(`${e.rack}:${e.well}`);
        tips[e.dev] = true;
      }
      continue;
    }
    if (e.type === "tipDrop") {
      if (T >= e.t) {
        tips[e.dev] = false;
        tipComp[e.dev] = {};
      }
      continue;
    }
    if (e.type !== "move" || T <= e.t0) continue;
    const f = Math.min(1, (T - e.t0) / (e.t1 - e.t0));
    const src = e.from.startsWith("tip:") ? tipComp[e.dev] : wells.get(e.from)!;
    const dst = e.to.startsWith("tip:") ? tipComp[e.dev] : wells.get(e.to)!;
    const amount = e.all ? total(src) * (f >= 1 ? 1 : f) : e.vol * f;
    merge(dst, take(src, amount));
  }
  return { wells, tips, tipComp, used };
}

export function gantryAt(segs: GantrySeg[], T: number, fallback: Vec3): Vec3 {
  if (!segs.length) return fallback;
  if (T <= segs[0].t0) return segs[0].p0;
  for (const s of segs)
    if (T < s.t1) {
      if (T < s.t0) return s.p0;
      const u = (T - s.t0) / (s.t1 - s.t0),
        e = u * u * (3 - 2 * u);
      return [0, 1, 2].map((i) => s.p0[i] + (s.p1[i] - s.p0[i]) * e) as Vec3;
    }
  return segs[segs.length - 1].p1;
}
