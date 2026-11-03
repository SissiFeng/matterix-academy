// UR5e nominal DH kinematics, nearby IK and automatic quintic timing.
// Ported from ur5e-sila-connector io/kinematics.py and io/action_chain.py; same limits and timing rule.

export type Mat4 = number[][];
export type Waypoint = {
  name: string;
  degrees: number[];
  hold: number;
  grip: "close" | "open" | null;
};
export type Segment = {
  t0: number;
  T: number;
  co: number[][];
  index: number;
  kind: "travel" | "hold";
};
export type Plan = {
  segs: Segment[];
  total: number;
  peakV: number;
  peakA: number;
  speed: number;
  rows: (Waypoint & { duration: number })[];
};

const A = [0, -0.425, -0.3922, 0, 0, 0];
const D = [0.1625, 0, 0, 0.1333, 0.0997, 0.0996];
const AL = [Math.PI / 2, 0, 0, Math.PI / 2, -Math.PI / 2, 0];
export const LIMIT_DEG = [355, 355, 155, 355, 355, 355];
export const NAMES = [
  "Base",
  "Shoulder",
  "Elbow",
  "Wrist 1",
  "Wrist 2",
  "Wrist 3",
];
export const DEG = Math.PI / 180;
const DT = 0.008;

const eye = (): Mat4 => [
  [1, 0, 0, 0],
  [0, 1, 0, 0],
  [0, 0, 1, 0],
  [0, 0, 0, 1],
];
export function mul(a: Mat4, b: Mat4): Mat4 {
  const r = eye();
  for (let i = 0; i < 4; i++)
    for (let j = 0; j < 4; j++) {
      let s = 0;
      for (let k = 0; k < 4; k++) s += a[i][k] * b[k][j];
      r[i][j] = s;
    }
  return r;
}
function dh(t: number, a: number, d: number, al: number): Mat4 {
  const c = Math.cos(t),
    s = Math.sin(t),
    ca = Math.cos(al),
    sa = Math.sin(al);
  return [
    [c, -s * ca, s * sa, a * c],
    [s, c * ca, -c * sa, a * s],
    [0, sa, ca, d],
    [0, 0, 0, 1],
  ];
}
/** Frames 0..6 for joint angles in radians, then the TCP frame offset along the flange Z. */
export function frames(q: number[], tcpZ = 0): Mat4[] {
  const out = [eye()];
  let m = eye();
  for (let i = 0; i < 6; i++) {
    m = mul(m, dh(q[i], A[i], D[i], AL[i]));
    out.push(m);
  }
  const t = eye();
  t[2][3] = tcpZ;
  out.push(mul(m, t));
  return out;
}
export const fk = (q: number[], tcpZ = 0) => frames(q, tcpZ)[7];

function rotvec(R: number[][]): number[] {
  const tr = R[0][0] + R[1][1] + R[2][2];
  const ang = Math.acos(Math.max(-1, Math.min(1, (tr - 1) / 2)));
  const sk = [R[2][1] - R[1][2], R[0][2] - R[2][0], R[1][0] - R[0][1]];
  if (ang < 1e-7) return sk.map((v) => v / 2);
  if (Math.PI - ang < 1e-5) {
    let idx = 0;
    for (let i = 1; i < 3; i++) if (R[i][i] > R[idx][idx]) idx = i;
    const ax = [0, 0, 0];
    ax[idx] = Math.sqrt(Math.max(0, (R[idx][idx] + 1) / 2));
    for (let j = 0; j < 3; j++)
      if (j !== idx) ax[j] = (R[idx][j] + R[j][idx]) / (4 * ax[idx]);
    if (ax[0] * sk[0] + ax[1] * sk[1] + ax[2] * sk[2] < 0)
      ax.forEach((v, i) => (ax[i] = -v));
    return ax.map((v) => v * ang);
  }
  return sk.map((v) => (ang * v) / (2 * Math.sin(ang)));
}
function err(cur: Mat4, tgt: Mat4): number[] {
  const R = [
    [0, 0, 0],
    [0, 0, 0],
    [0, 0, 0],
  ];
  for (let i = 0; i < 3; i++)
    for (let j = 0; j < 3; j++) {
      let s = 0;
      for (let k = 0; k < 3; k++) s += tgt[i][k] * cur[j][k];
      R[i][j] = s;
    }
  return [
    tgt[0][3] - cur[0][3],
    tgt[1][3] - cur[1][3],
    tgt[2][3] - cur[2][3],
    ...rotvec(R),
  ];
}
function solve(M: number[][], b: number[]): number[] | null {
  const n = b.length,
    r = M.map((row, i) => [...row, b[i]]);
  for (let i = 0; i < n; i++) {
    let p = i;
    for (let j = i + 1; j < n; j++)
      if (Math.abs(r[j][i]) > Math.abs(r[p][i])) p = j;
    [r[i], r[p]] = [r[p], r[i]];
    const s = r[i][i];
    if (Math.abs(s) < 1e-16) return null;
    for (let k = i; k <= n; k++) r[i][k] /= s;
    for (let j = 0; j < n; j++)
      if (j !== i) {
        const f = r[j][i];
        for (let k = i; k <= n; k++) r[j][k] -= f * r[i][k];
      }
  }
  return r.map((row) => row[n]);
}
export const withinLimits = (q: number[]) =>
  q.every((v, i) => Math.abs(v / DEG) < LIMIT_DEG[i]);

/** Tool pointing straight down; fingers rotated by `yaw` about the base Z. */
export function downPose(x: number, y: number, z: number, yaw: number): Mat4 {
  const c = Math.cos(yaw),
    s = Math.sin(yaw);
  return [
    [c, s, 0, x],
    [s, -c, 0, y],
    [0, 0, -1, z],
    [0, 0, 0, 1],
  ];
}

/** Nearby damped least-squares IK, the connector's scheme: no angle wrapping. */
export function ik(target: Mat4, seed: number[], tcpZ: number) {
  let q = seed.slice();
  const w = [1, 1, 1, 0.25, 0.25, 0.25];
  const idx = [0, 1, 2, 3, 4, 5];
  for (let it = 0; it < 220; it++) {
    const cur = fk(q, tcpZ),
      e = err(cur, target);
    const pe = Math.hypot(e[0], e[1], e[2]),
      oe = Math.hypot(e[3], e[4], e[5]);
    if (pe < 0.0002 && oe < 0.002)
      return withinLimits(q) ? { q, pe, oe } : null;
    const J: number[][] = [];
    for (let j = 0; j < 6; j++) {
      const sh = q.slice();
      sh[j] += 1e-6;
      J.push(err(cur, fk(sh, tcpZ)).map((v) => v / 1e-6));
    }
    const Jw = idx.map((i) => J.map((c) => c[i] * w[i]));
    const ew = e.map((v, i) => v * w[i]);
    const N = idx.map((i) =>
      idx.map((j) => {
        let s = 0;
        for (let k = 0; k < 6; k++) s += Jw[k][i] * Jw[k][j];
        return s + (i === j ? 1e-4 : 0);
      }),
    );
    const rhs = idx.map((i) => {
      let s = 0;
      for (let k = 0; k < 6; k++) s += Jw[k][i] * ew[k];
      return s;
    });
    const dq = solve(N, rhs);
    if (!dq) return null;
    const sc = Math.min(1, 0.15 / Math.max(1e-10, ...dq.map(Math.abs)));
    q = q.map((v, i) => v + sc * dq[i]);
    if (!withinLimits(q)) return null;
  }
  return null;
}

/** Automatic timing (build_at_speed) and the C2 quintic with shared knot tangents (build). */
export function plan(
  startDeg: number[],
  waypoints: Waypoint[],
  speed: number,
): Plan | { error: string } {
  const pts = [startDeg, ...waypoints.map((w) => w.degrees)];
  let rows = waypoints.map((w, i) => {
    const dist = Math.max(...w.degrees.map((v, j) => Math.abs(v - pts[i][j])));
    const sec = Math.max(
      1,
      (1.03 * 1.875 * dist) / speed,
      1.03 * Math.sqrt((5.774 * dist) / (2 * speed)),
    );
    return {
      ...w,
      duration: Math.ceil(sec / DT) * DT,
      hold: Math.round((w.hold || 0) / DT) * DT,
    };
  });
  for (let attempt = 0; attempt < 5; attempt++) {
    const built = build(pts, rows);
    const cap = speed * 0.8;
    if (built.peakV <= cap && built.peakA <= 2 * cap)
      return { ...built, speed, rows };
    const sc =
      Math.max(built.peakV / cap, Math.sqrt(built.peakA / (1.6 * speed))) *
      1.03;
    rows = rows.map((r) => ({
      ...r,
      duration: Math.ceil((r.duration * sc) / DT) * DT,
    }));
  }
  return {
    error:
      "No checked trajectory fits the automatic timing bounds. Split the action.",
  };
}
function build(pts: number[][], rows: { duration: number; hold: number }[]) {
  const vel = pts.map(() => [0, 0, 0, 0, 0, 0]);
  for (let i = 1; i < pts.length - 1; i++) {
    if (rows[i - 1].hold) continue;
    for (let j = 0; j < 6; j++) {
      const l = (pts[i][j] - pts[i - 1][j]) / rows[i - 1].duration;
      const r = (pts[i + 1][j] - pts[i][j]) / rows[i].duration;
      if (l * r > 0)
        vel[i][j] = Math.sign(l) * Math.min(Math.abs(l), Math.abs(r));
    }
  }
  const segs: Segment[] = [];
  let t = 0;
  rows.forEach((row, i) => {
    const T = row.duration;
    const co = [0, 1, 2, 3, 4, 5].map((j) => {
      const a = pts[i][j],
        b = pts[i + 1][j],
        v = vel[i][j] * T,
        w = vel[i + 1][j] * T,
        d = b - a;
      return [
        a,
        v,
        0,
        10 * d - 6 * v - 4 * w,
        -15 * d + 8 * v + 7 * w,
        6 * d - 3 * v - 3 * w,
      ];
    });
    segs.push({ t0: t, T, co, index: i, kind: "travel" });
    t += T;
    if (row.hold) {
      segs.push({
        t0: t,
        T: row.hold,
        co: pts[i + 1].map((v) => [v, 0, 0, 0, 0, 0]),
        index: i,
        kind: "hold",
      });
      t += row.hold;
    }
  });
  const total = t;
  let peakV = 0,
    peakA = 0,
    prev: number[] | null = null,
    prevV: number[] | null = null;
  for (let k = 0; k <= Math.round(total / DT); k++) {
    const q = sample(segs, k * DT);
    if (prev) {
      const v = q.map((x, j) => (x - prev![j]) / DT);
      peakV = Math.max(peakV, ...v.map(Math.abs));
      if (prevV)
        peakA = Math.max(
          peakA,
          ...v.map((x, j) => Math.abs((x - prevV![j]) / DT)),
        );
      prevV = v;
    }
    prev = q;
  }
  return { segs, total, peakV, peakA };
}
export function sample(segs: Segment[], t: number): number[] {
  let s = segs[segs.length - 1];
  for (const g of segs)
    if (t < g.t0 + g.T) {
      s = g;
      break;
    }
  const u = Math.max(0, Math.min(1, (t - s.t0) / s.T));
  return s.co.map(
    (c) => c[0] + u * (c[1] + u * (c[2] + u * (c[3] + u * (c[4] + u * c[5])))),
  );
}
