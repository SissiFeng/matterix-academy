// The 3D workcell: scene, arm editing, workflow compilation, playback and the scripted demo.
// React renders the panels from `Snapshot`; this module owns Three.js and all timing.
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { GLTF } from "three/examples/jsm/loaders/GLTFLoader.js";
import { Line2 } from "three/examples/jsm/lines/Line2.js";
import { LineGeometry } from "three/examples/jsm/lines/LineGeometry.js";
import { LineMaterial } from "three/examples/jsm/lines/LineMaterial.js";
import * as K from "./kin";
import * as C from "./cell";
import * as W from "./workflow";
import { Liquids, reservoir, tipRack, tubeRack, type TipRack } from "./labware";
import { buildOT2 } from "./ot2Model";
import { buildBalance } from "./balanceModel";
import { buildRobot, thetaForGap } from "./robotModel";

const DEG = K.DEG;
const FLEX_REACH = 0.0851;
const FLEX_PARK: C.Vec3 = [0.05, 0.38, 0.29];
const THETA_OPEN = thetaForGap(C.GAP_OPEN),
  THETA_RACK = thetaForGap(C.GAP_CLOSED);
const SAMPLE_DT = 0.05;
const HOUSING_CENTRE = [0.06, 0.07, 0.07, 0.0075, 0, 0.0175];
const STORE = "academy.workcell-case.synthesis-cell.v1";

export type CaseAssets = {
  decks: C.Decks;
  labware: C.LabwareSet;
  flexMeta: { bodies: Record<string, number[][]> };
  flex: GLTF;
  robot: GLTF;
};
export type Lane = "flex" | "ot2" | "ur" | "bal";
export type Level = "ok" | "warn" | "bad";
export type Issue = { level: Level; text: string };
export type Stage = {
  lane: Lane;
  label: string;
  t0: number;
  t1: number;
  blocked?: boolean;
  weigh?: boolean;
};
export type LogEntry = {
  t: number;
  dev: Lane | "cell" | "design";
  text: string;
  stamp?: string;
};
export type View = "cell" | "flex" | "balance" | "ot2";
export type Snapshot = {
  t: number;
  total: number;
  playing: boolean;
  editing: boolean;
  demo: { active: boolean; playing: boolean; title: string; sub: string };
  joint: number;
  pose: number[];
  gripClosed: boolean;
  canUndo: boolean;
  sel: number;
  visible: number;
  current: number;
  speed: number;
  chain: (K.Waypoint & { travel: number | null; issues: Issue[] })[];
  plan: { total: number; peakV: number; hitSeconds: number } | null;
  planMsg: { level: Level; text: string };
  flowMsg: { level: Level; text: string };
  stages: (Stage & {
    status: "done" | "now" | "pending" | "blocked";
    sub: string;
  })[];
  log: LogEntry[];
  balance: { text: string; stable: boolean; note: string };
  devices: { flex: string; ot2: string; ur: string };
  rack: string;
  vials: {
    well: string;
    total: number;
    solvent: number;
    substrate: number;
    reagent: number;
    catalyst: number;
    mg: number;
    rgb: C.Vec3;
  }[];
  status: string;
  toggles: { trails: boolean; path: boolean; keepouts: boolean };
  message: { level: Level; text: string } | null;
};
export type ChartData = {
  total: number;
  samples: [number, number[]][];
  arrive: number[];
  hits: number[];
  cursor: number | null;
};

const LOC: Record<string, string> = {
  flex: "On Flex D2",
  arm: "In the gripper",
  balance: "On the balance",
  ot2: "In OT-2 slot 2",
  "ot2-rotated": "OT-2 slot 2, rotated 180°",
  air: "Released off-station",
};
const VIEWS: Record<string, { pos: C.Vec3; target: C.Vec3 }> = {
  cell: { pos: [0.05, 1.75, 2.75], target: [0.03, 0.12, -0.02] },
  flex: { pos: [-0.05, 0.78, 0.38], target: [0.58, 0.16, -0.04] },
  balance: { pos: [0.32, 0.55, 1.05], target: [0.0, 0.1, 0.42] },
  ot2: { pos: [-0.5, 0.98, 0.72], target: [-0.64, 0.1, 0.1] },
  ot2run: { pos: [-0.2, 0.86, 0.78], target: [-0.62, 0.12, 0.06] },
  design: { pos: [0.16, 1.32, 1.95], target: [0.02, 0.22, -0.04] },
};
const WELL_NAME = (key: string) => {
  const [a, b, c] = key.split(":");
  if (a === "rack") return `vial ${b}`;
  if (b === "solvent") return "Flex B1 solvent";
  if (b === "stocks") return `Flex B2 stock ${c}`;
  if (b === "reagents")
    return c === "A1" ? "OT-2 slot 4 reagent R" : "OT-2 slot 4 catalyst C";
  if (b === "mixes") return `OT-2 slot 3 tube ${c}`;
  return key;
};
const smooth = (u: number) => {
  u = Math.max(0, Math.min(1, u));
  return u * u * (3 - 2 * u);
};
const m4 = (F: K.Mat4) =>
  new THREE.Matrix4().set(
    ...(F.flat() as [
      number,
      number,
      number,
      number,
      number,
      number,
      number,
      number,
      number,
      number,
      number,
      number,
      number,
      number,
      number,
      number,
    ]),
  );
const tcpM = (deg: number[]) =>
  m4(
    K.fk(
      deg.map((v) => v * DEG),
      C.TCP,
    ),
  );

type ArmState = {
  loc: string;
  offset: THREE.Matrix4 | null;
  M: THREE.Matrix4;
  tcp: THREE.Vector3;
};
type Compiled = {
  prep: W.Prep;
  plan: K.Plan | null;
  urStart: number;
  arrive: number[];
  leave: number[];
  grips: { t0: number; t1: number; from: number; to: number }[];
  rackTimeline: (
    | { t: number; kind: "place"; M: THREE.Matrix4; loc: string }
    | { t: number; kind: "attach"; offset: THREE.Matrix4 }
  )[];
  arm: { states: ArmState[]; issues: Issue[][] };
  events: W.LiquidEvent[];
  total: number;
  stages: Stage[];
  planMsg: { level: Level; text: string } | null;
  flowMsg: { level: Level; text: string };
  hits: number[];
  release: Record<string, number>;
  regrip: number | null;
  log: LogEntry[];
};

export class CellEngine {
  onChange: (s: Snapshot) => void = () => {};
  onChart: (c: ChartData) => void = () => {};
  private readonly host: HTMLElement;
  private readonly tokens: HTMLElement;
  private readonly a: CaseAssets;
  private readonly stations;
  private readonly labwareBoxes: C.Box[];
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera = new THREE.PerspectiveCamera(34, 1, 0.02, 30);
  private controls: OrbitControls;
  private root = new THREE.Group();
  private flexFrame: THREE.Group;
  private ot2Frame: THREE.Group;
  private liquids = new Liquids();
  private flexParts: Record<string, THREE.Group> = {};
  private flexTips = new Map<string, THREE.Object3D>();
  private flexPipTip: THREE.Object3D[] = [];
  private flexPipLiq: THREE.Object3D[] = [];
  private flexHome: Record<string, THREE.Vector3> = {};
  private ot2;
  private ot2Tips: TipRack;
  private rack: THREE.Group;
  private balance;
  private robot;
  private RACK0: THREE.Matrix4;
  private RACK_OT2: THREE.Matrix4;
  private benchMat = new THREE.MeshStandardMaterial({ roughness: 0.9 });
  private benchEdge: THREE.LineSegments;
  private keepGroup = new THREE.Group();
  private keepMat = new THREE.MeshBasicMaterial({
    transparent: true,
    opacity: 0.08,
    depthWrite: false,
  });
  private keepEdge = new THREE.LineBasicMaterial({
    transparent: true,
    opacity: 0.6,
  });
  private pathMat = new LineMaterial({
    linewidth: 3,
    vertexColors: true,
    transparent: true,
  });
  private pathLine: Line2 | null = null;
  private markers = new THREE.Group();
  private trailGroup = new THREE.Group();
  private trails: Line2[] = [];
  private trailDots: { t: number; set: THREE.Mesh[] }[] = [];
  private ringMat = new THREE.MeshBasicMaterial({
    transparent: true,
    opacity: 0.9,
    depthTest: false,
  });
  private ring: THREE.Mesh;
  private ringHit: THREE.Mesh;
  private ringInfo = { c: new THREE.Vector3(), z: new THREE.Vector3(0, 0, 1) };
  private labels: { el: HTMLDivElement; pos: THREE.Vector3 }[] = [];
  private raf = 0;
  private last = performance.now();
  private lastEmit = 0;
  private frozen = false;
  private disposed = false;
  private drag: { a: number; start: number } | null = null;
  private observer: ResizeObserver;
  private themeObserver: MutationObserver;
  private media = window.matchMedia("(prefers-color-scheme: dark)");
  private wf!: Compiled;
  private toggles = { trails: true, path: true, keepouts: false };
  private message: { level: Level; text: string } | null = null;
  private messageTimer = 0;
  private S = {
    pose: C.HOME.slice(),
    undo: [] as number[][],
    joint: 0,
    chain: [] as K.Waypoint[],
    sel: -1,
    speed: 30,
    t: 0,
    playing: false,
    rate: 8,
    mode: "playback" as "playback" | "editor",
    gripClosed: false,
  };
  private D = {
    active: false,
    playing: false,
    tau: 0,
    step: 1.8,
    intro: 2.5,
    validate: 2.4,
    outro: 4,
    visible: 0,
    designStart: 0,
    designEnd: 0,
    runStart: Infinity,
    runEnd: 0,
    duration: 0,
    title: "",
    sub: "",
    how: [] as string[],
    designLog: [] as (LogEntry & { at: number })[],
    map: [] as { T0: number; T1: number; rate: number; tau0: number }[],
    cams: [] as { tau: number; v: string }[],
  };

  constructor(host: HTMLElement, tokens: HTMLElement, assets: CaseAssets) {
    this.host = host;
    this.tokens = tokens;
    this.a = assets;
    this.stations = C.stations(assets.decks);
    this.labwareBoxes = C.labwareBoxes(assets.decks, assets.labware);
    this.renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: true,
      preserveDrawingBuffer: true,
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    host.prepend(this.renderer.domElement);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.maxPolarAngle = Math.PI * 0.495;
    this.controls.minDistance = 0.35;
    this.controls.maxDistance = 6;
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x8c968f, 1.9));
    const sun = new THREE.DirectionalLight(0xffffff, 1.7);
    sun.position.set(1.2, 3.2, 2.2);
    this.scene.add(sun);
    const fill = new THREE.DirectionalLight(0xffffff, 0.6);
    fill.position.set(-2, 1.5, -1);
    this.scene.add(fill);
    this.root.rotation.x = -Math.PI / 2;
    this.scene.add(this.root);
    this.setView("cell");

    const bench = new THREE.Mesh(
      new THREE.BoxGeometry(2.3, 1.45, 0.04),
      this.benchMat,
    );
    bench.position.set(0.05, 0.02, -0.02);
    this.root.add(bench);
    this.benchEdge = new THREE.LineSegments(
      new THREE.EdgesGeometry(bench.geometry),
      new THREE.LineBasicMaterial({ transparent: true, opacity: 0.4 }),
    );
    bench.add(this.benchEdge);
    const frameGroup = (frame: C.Frame) => {
      const f = C.FRAMES[frame],
        g = new THREE.Group();
      g.position.set(...f.t);
      g.rotation.z = f.yaw;
      this.root.add(g);
      return g;
    };
    this.flexFrame = frameGroup("flex");
    this.ot2Frame = frameGroup("ot2");
    this.root.updateMatrixWorld(true);
    this.buildFlex();
    const L = C.LAYOUT;
    const place = (g: THREE.Object3D, frame: C.Frame, slot: string) =>
      g.position.set(...C.slotOrigin(assets.decks, frame, slot));
    const lw = assets.labware;
    this.ot2 = buildOT2(assets.decks.ot2);
    this.ot2Frame.add(this.ot2.group);
    this.ot2Tips = tipRack(lw[L.ot2.tips.def]);
    place(this.ot2Tips, "ot2", L.ot2.tips.slot);
    this.ot2Frame.add(this.ot2Tips);
    const res = reservoir(lw[L.ot2.reagents.def], this.liquids, "ot2:reagents");
    place(res, "ot2", L.ot2.reagents.slot);
    this.ot2Frame.add(res);
    const mixes = tubeRack(lw[L.ot2.mixes.def], this.liquids, "ot2:mixes", {
      tubes: W.VIALS,
      cap: 0xf3f4f5,
      screw: false,
    });
    place(mixes, "ot2", L.ot2.mixes.slot);
    this.ot2Frame.add(mixes);
    this.rack = tubeRack(lw[L.flex.rack.def], this.liquids, "rack", {
      tubes: W.VIALS,
      cap: 0x2f6fb0,
      screw: true,
    });
    this.rack.matrixAutoUpdate = false;
    this.root.add(this.rack);
    this.balance = buildBalance();
    this.root.add(this.balance.group);
    this.robot = buildRobot(assets.robot);
    this.root.add(this.robot.group);
    const rackAt = (f: THREE.Group, frame: C.Frame, slot: string) =>
      new THREE.Matrix4()
        .copy(f.matrix)
        .multiply(
          new THREE.Matrix4().makeTranslation(
            ...C.slotOrigin(assets.decks, frame, slot),
          ),
        );
    this.RACK0 = rackAt(this.flexFrame, "flex", L.flex.rack.slot);
    this.RACK_OT2 = rackAt(this.ot2Frame, "ot2", L.ot2.rack.slot);

    this.label("Flex", C.toRobot("flex", [0.05, 0.15, 0.7]));
    this.label("OT-2", C.toRobot("ot2", [0.2, 0.17, 0.6]));
    this.label("Balance", [
      C.BALANCE.centre[0],
      C.BALANCE.centre[1] - 0.12,
      0.13,
    ]);
    this.label("UR5e", [0, 0.12, 0.02]);
    this.keepGroup.visible = false;
    this.root.add(this.keepGroup);
    for (const b of [...C.keepouts(), ...this.labwareBoxes])
      if (b.owner !== "Bench") {
        const s = [0, 1, 2].map((i) => b.max[i] - b.min[i]),
          g = new THREE.BoxGeometry(s[0], s[1], s[2]);
        const m = new THREE.Mesh(g, this.keepMat);
        m.position.set(
          ...([0, 1, 2].map((i) => (b.min[i] + b.max[i]) / 2) as C.Vec3),
        );
        m.add(
          new THREE.LineSegments(new THREE.EdgesGeometry(g), this.keepEdge),
        );
        this.keepGroup.add(m);
      }
    this.root.add(this.markers, this.trailGroup);
    this.ring = new THREE.Mesh(
      new THREE.TorusGeometry(0.1, 0.005, 10, 72),
      this.ringMat,
    );
    this.ring.renderOrder = 10;
    this.ringHit = new THREE.Mesh(
      new THREE.TorusGeometry(0.1, 0.03, 8, 48),
      new THREE.MeshBasicMaterial({ visible: false }),
    );
    this.root.add(this.ring, this.ringHit);

    try {
      const saved = JSON.parse(localStorage.getItem(STORE) || "null");
      if (saved?.chain?.length) {
        this.S.chain = saved.chain;
        this.S.speed = saved.speed || 30;
      }
    } catch {
      /* Storage may be unavailable; the default chain is used. */
    }
    if (!this.S.chain.length) this.S.chain = C.generateTransfer(this.stations);

    const el = this.renderer.domElement;
    el.addEventListener("pointerdown", this.pointerDown);
    el.addEventListener("pointermove", this.pointerMove);
    el.addEventListener("pointerup", this.endDrag);
    el.addEventListener("pointercancel", this.endDrag);
    window.addEventListener("keydown", this.keyDown);
    this.observer = new ResizeObserver(() => this.resize());
    this.observer.observe(host);
    this.themeObserver = new MutationObserver(() => this.applyTheme());
    this.themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
    this.media.addEventListener("change", this.applyTheme);
    this.resize();
    this.applyTheme();
    this.raf = requestAnimationFrame(this.tick);
  }

  // ---------- Construction helpers ----------
  private css(name: string) {
    return (
      getComputedStyle(this.tokens).getPropertyValue(name).trim() || "#888888"
    );
  }
  private label(text: string, pos: number[]) {
    const el = document.createElement("div");
    el.dataset.label = "";
    el.textContent = text;
    this.host.appendChild(el);
    this.labels.push({ el, pos: new THREE.Vector3(pos[0], pos[1], pos[2]) });
  }
  private buildFlex() {
    for (const n of [...this.a.flex.scene.children]) {
      const [body, geom] = n.name.split("|");
      if (!this.flexParts[body]) {
        this.flexParts[body] = new THREE.Group();
        this.flexFrame.add(this.flexParts[body]);
      }
      this.flexParts[body].add(n);
      if (geom?.startsWith("tips_")) this.flexTips.set(geom.slice(5), n);
      if (geom === "pipette_1000_tip") this.flexPipTip.push(n);
      if (geom === "pipette_1000_tip_liquid") this.flexPipLiq.push(n);
    }
    for (const n of [...this.flexPipTip, ...this.flexPipLiq])
      n.traverse((o) => {
        const mesh = o as THREE.Mesh;
        if (mesh.isMesh) {
          mesh.material = (mesh.material as THREE.Material).clone();
          (mesh.material as THREE.Material).transparent = true;
        }
      });
    const door = new THREE.Group();
    door.position.set(0, -0.17, 0.612);
    this.flexFrame.add(door);
    if (this.flexParts.door) {
      this.flexParts.door.position.set(0, 0.17, -0.612);
      door.add(this.flexParts.door);
      door.rotation.x = -Math.PI + 0.12;
    }
    for (const k of [
      "bridge",
      "carriage",
      "pip",
      "gripper",
      "jaw_f",
      "jaw_b",
    ]) {
      const b = this.a.flexMeta.bodies[k];
      this.flexHome[k] = b
        ? new THREE.Vector3(b[0][3], b[1][3], b[2][3])
        : new THREE.Vector3();
    }
    const lw = this.a.labware,
      L = C.LAYOUT.flex;
    const solvent = new THREE.Group();
    solvent.position.set(...C.slotOrigin(this.a.decks, "flex", L.solvent.slot));
    this.flexFrame.add(solvent);
    this.liquids.add(
      "flex:solvent:A1",
      lw[L.solvent.def].wells.A1,
      solvent,
      "rect",
    );
    const stocks = tubeRack(lw[L.stocks.def], this.liquids, "flex:stocks", {
      tubes: W.VIALS,
      cap: 0xe7a33a,
      screw: false,
    });
    stocks.position.set(...C.slotOrigin(this.a.decks, "flex", L.stocks.slot));
    this.flexFrame.add(stocks);
  }
  private setFlexNozzle(N: C.Vec3) {
    const q = [N[0], N[1], N[2] - FLEX_REACH],
      P = this.flexParts,
      H = this.flexHome;
    P.bridge?.position.copy(H.bridge).add(new THREE.Vector3(0, q[1], 0));
    P.carriage?.position.copy(H.carriage).add(new THREE.Vector3(q[0], q[1], 0));
    P.pip?.position.copy(H.pip).add(new THREE.Vector3(q[0], q[1], q[2]));
    for (const k of ["gripper", "jaw_f", "jaw_b"])
      P[k]?.position.copy(H[k]).add(new THREE.Vector3(q[0], q[1], 0.21));
  }

  // ---------- Arm chain → rack states ----------
  private simulateArm(chain: K.Waypoint[]) {
    const { RACK0, RACK_OT2 } = this;
    const R = C.RACK;
    const centreOf = (M: THREE.Matrix4) =>
      new THREE.Vector3(R.L / 2, R.W / 2, 0).applyMatrix4(M);
    const xDir = (M: THREE.Matrix4) =>
      new THREE.Vector3(1, 0, 0).transformDirection(M);
    const aroundCentre = (M: THREE.Matrix4, yaw: number) => {
      const c = centreOf(M);
      return new THREE.Matrix4()
        .makeTranslation(c.x, c.y, c.z)
        .multiply(new THREE.Matrix4().makeRotationZ(yaw))
        .multiply(new THREE.Matrix4().makeTranslation(-c.x, -c.y, -c.z))
        .multiply(M);
    };
    let M = RACK0.clone(),
      loc = "flex",
      offset: THREE.Matrix4 | null = null;
    const states: ArmState[] = [],
      issues: Issue[][] = chain.map(() => []);
    chain.forEach((w, i) => {
      const q = w.degrees.map((v) => v * DEG);
      if (!K.withinLimits(q))
        issues[i].push({ level: "bad", text: "Inside joint limit margin" });
      const hits = C.clearance(q);
      if (hits.length)
        issues[i].push({
          level: "bad",
          text: `${hits[0].link} hits ${hits[0].owner} ${hits[0].part}`,
        });
      const T = tcpM(w.degrees),
        tp = new THREE.Vector3().setFromMatrixPosition(T);
      if (w.grip === "close") {
        if (offset)
          issues[i].push({ level: "warn", text: "Already holding the rack" });
        else {
          const gp = centreOf(M).add(new THREE.Vector3(0, 0, R.grip));
          if (
            Math.hypot(tp.x - gp.x, tp.y - gp.y) < 0.015 &&
            Math.abs(tp.z - gp.z) < 0.012
          ) {
            offset = T.clone().invert().multiply(M);
            loc = "arm";
          } else
            issues[i].push({ level: "warn", text: "Nothing to grip here" });
        }
      }
      if (w.grip === "open") {
        if (!offset)
          issues[i].push({ level: "warn", text: "Gripper already open" });
        else {
          const carried = T.clone().multiply(offset),
            c = centreOf(carried);
          const near = (P: THREE.Matrix4, z: number) => {
            const p = centreOf(P);
            return (
              Math.hypot(p.x - c.x, p.y - c.y) < 0.02 &&
              c.z - z > -0.006 &&
              c.z - z < 0.02
            );
          };
          const aligned = (P: THREE.Matrix4) => xDir(P).dot(xDir(carried));
          if (near(RACK0, C.FRAMES.flex.deckZ)) {
            M =
              aligned(RACK0) > 0 ? RACK0.clone() : aroundCentre(RACK0, Math.PI);
            loc = "flex";
          } else if (near(RACK_OT2, C.FRAMES.ot2.deckZ)) {
            const ok = aligned(RACK_OT2) > 0;
            M = ok ? RACK_OT2.clone() : aroundCentre(RACK_OT2, Math.PI);
            if (!ok)
              issues[i].push({
                level: "bad",
                text: "Rack sits rotated 180°; vials face the wrong way",
              });
            loc = ok ? "ot2" : "ot2-rotated";
          } else if (
            Math.hypot(c.x - C.BALANCE.pan[0], c.y - C.BALANCE.pan[1]) < 0.03 &&
            Math.abs(c.z - C.BALANCE.pan[2]) < 0.02
          ) {
            const yaw =
              Math.round(
                Math.atan2(xDir(carried).y, xDir(carried).x) / (Math.PI / 2),
              ) *
              (Math.PI / 2);
            M = new THREE.Matrix4()
              .makeTranslation(...C.BALANCE.pan)
              .multiply(new THREE.Matrix4().makeRotationZ(yaw))
              .multiply(
                new THREE.Matrix4().makeTranslation(-R.L / 2, -R.W / 2, 0),
              );
            loc = "balance";
          } else {
            M = carried;
            loc = "air";
            issues[i].push({
              level: "bad",
              text: "Released away from a station",
            });
          }
          offset = null;
        }
      }
      states.push({ loc, offset, M: M.clone(), tcp: tp });
    });
    return { states, issues };
  }
  private rackBox(M: THREE.Matrix4): C.Box {
    const pts = [0, 1].flatMap((a) =>
      [0, 1].flatMap((b) =>
        [0, 1].map((c) =>
          new THREE.Vector3(
            a * C.RACK.L,
            b * C.RACK.W,
            c * C.RACK.H,
          ).applyMatrix4(M),
        ),
      ),
    );
    const lo = [0, 1, 2].map((i) =>
        Math.min(...pts.map((p) => p.getComponent(i))),
      ),
      hi = [0, 1, 2].map((i) => Math.max(...pts.map((p) => p.getComponent(i))));
    return {
      owner: "Sample rack",
      part: "vials",
      min: lo as C.Vec3,
      max: hi as C.Vec3,
    };
  }

  // ---------- Compile ----------
  private compile() {
    const S = this.S,
      a = this.a;
    const prep = W.buildPrep(a.decks, a.labware, {
      flex: { reach: FLEX_REACH, park: FLEX_PARK },
      ot2: {
        reach: this.ot2.REACH,
        park: this.ot2.park,
        trash: this.ot2.trash,
      },
    });
    const urStart = prep.end + 1;
    const arm = this.simulateArm(S.chain);
    let plan: K.Plan | null = null,
      planMsg: Compiled["planMsg"] = null;
    if (!S.chain.length)
      planMsg = { level: "warn", text: "Add waypoints to move the rack." };
    else if (S.chain.length > 24)
      planMsg = { level: "bad", text: "The connector accepts 1–24 waypoints." };
    else {
      const p = K.plan(C.HOME, S.chain, S.speed);
      if ("error" in p) planMsg = { level: "bad", text: p.error };
      else plan = p;
    }
    const grips: Compiled["grips"] = [];
    const rackTimeline: Compiled["rackTimeline"] = [
      { t: -1, kind: "place", M: this.RACK0, loc: "flex" },
    ];
    const release: Record<string, number> = {};
    let regrip: number | null = null,
      otClear: number | null = null;
    const hits: number[] = [];
    let arrive: number[] = [],
      leave: number[] = [];
    if (plan) {
      for (const g of plan.segs) {
        if (g.kind === "travel") arrive[g.index] = g.t0 + g.T;
        leave[g.index] = g.t0 + g.T;
      }
      const ra = arrive.slice();
      arrive = arrive.map((x) => x + urStart);
      leave = leave.map((x) => x + urStart);
      S.chain.forEach((w, i) => {
        const t = arrive[i],
          st = arm.states[i],
          prev = i ? arm.states[i - 1] : { loc: "flex" };
        if (w.grip === "close") {
          grips.push({ t0: t, t1: t + 0.6, from: THETA_OPEN, to: THETA_RACK });
          if (st.loc === "arm" && prev.loc !== "arm") {
            rackTimeline.push({
              t: t + 0.6,
              kind: "attach",
              offset: st.offset!,
            });
            if (prev.loc === "balance") regrip = t + 0.6;
          }
        }
        if (w.grip === "open") {
          grips.push({ t0: t, t1: t + 0.6, from: THETA_RACK, to: THETA_OPEN });
          if (prev.loc === "arm" && st.loc !== "arm") {
            rackTimeline.push({
              t: t + 0.25,
              kind: "place",
              M: st.M,
              loc: st.loc,
            });
            release[st.loc] = t + 0.25;
          }
        }
        if (
          release.ot2 &&
          otClear === null &&
          i > 0 &&
          st.tcp.distanceTo(
            new THREE.Vector3(
              this.stations.ot2.x,
              this.stations.ot2.y,
              st.tcp.z,
            ),
          ) > 0.12
        )
          otClear = t;
      });
      if (release.ot2 && otClear === null) otClear = urStart + plan.total;
      // Colour the TCP path by phase and check links, fingers and the carried rack every 50 ms.
      const pts: number[] = [],
        cols: number[] = [];
      const cT = new THREE.Color(this.css("--info")),
        cA = new THREE.Color(this.css("--ok")),
        cC = new THREE.Color(this.css("--accent")),
        cH = new THREE.Color(this.css("--danger"));
      const homeTcp = new THREE.Vector3().setFromMatrixPosition(tcpM(C.HOME));
      const at = (list: Compiled["rackTimeline"], t: number) =>
        list.filter((e) => e.t <= t).at(-1);
      for (let u = 0; u <= plan.total + 1e-9; u += SAMPLE_DT) {
        let i = 0;
        while (i < ra.length - 1 && u > leave[i] - urStart) i++;
        const q = K.sample(plan.segs, u),
          qr = q.map((v) => v * DEG),
          f = K.fk(qr, C.TCP);
        pts.push(f[0][3], f[1][3], f[2][3]);
        const T = u + urStart,
          held = at(rackTimeline, T)?.kind === "attach";
        const placed = at(rackTimeline, T);
        const extra =
          !held && placed && placed.kind === "place"
            ? [this.rackBox(placed.M)]
            : [];
        const gap =
          this.gripAtFrom(grips, T) > (THETA_OPEN + THETA_RACK) / 2
            ? C.GAP_CLOSED
            : C.GAP_OPEN;
        const hit =
          C.clearance(qr).length > 0 ||
          C.toolClearance(qr, gap, held, [...this.labwareBoxes, ...extra])
            .length > 0;
        if (hit) hits.push(u);
        const a0 = i ? arm.states[i - 1].tcp : homeTcp,
          b0 = arm.states[i].tcp;
        const carrying = i > 0 && arm.states[i - 1].loc === "arm";
        const c = hit
          ? cH
          : carrying
            ? cC
            : Math.hypot(a0.x - b0.x, a0.y - b0.y) < 0.02
              ? cA
              : cT;
        cols.push(c.r, c.g, c.b);
      }
      if (this.pathLine) {
        this.root.remove(this.pathLine);
        this.pathLine.geometry.dispose();
      }
      const g = new LineGeometry();
      g.setPositions(pts);
      g.setColors(cols);
      this.pathLine = new Line2(g, this.pathMat);
      this.pathLine.visible = this.toggles.path;
      this.root.add(this.pathLine);
      this.buildTrails(plan, ra);
      if (plan.total > 120)
        planMsg = {
          level: "bad",
          text: `The arm action takes ${plan.total.toFixed(1)} s; the connector limit is 120 s.`,
        };
      else if (plan.rows.some((r) => r.duration > 60))
        planMsg = {
          level: "bad",
          text: "A segment needs over 60 s at this speed.",
        };
      else if (hits.length)
        planMsg = {
          level: "bad",
          text: `The arm, fingers or rack enter a keep-out for ${(hits.length * SAMPLE_DT).toFixed(2)} s.`,
        };
    }
    const reached = release.ot2 !== undefined;
    const synthEnd = reached
      ? W.addSynthesis(prep, (otClear ?? urStart) + 0.5)
      : null;
    const events = [...prep.F.events, ...prep.O.events].sort(
      (x, y) => W.eventTime(x) - W.eventTime(y),
    );
    const urEnd = plan ? urStart + plan.total : urStart;
    const total = Math.max(urEnd, synthEnd ?? 0, prep.end) + 2;
    const stages: Stage[] = [
      ...prep.F.ops.map((o) => ({ lane: "flex" as Lane, ...o })),
      ...prep.O.ops
        .filter((o) => o.label !== W.SYNTHESIS)
        .map((o) => ({ lane: "ot2" as Lane, ...o })),
    ];
    if (plan) {
      const bal = release.balance;
      stages.push({
        lane: "ur",
        label: "UR5e · Flex D2 → balance",
        t0: urStart,
        t1: bal ?? urEnd,
      });
      if (bal !== undefined)
        stages.push({
          lane: "bal",
          label: "Balance · Weigh sample rack",
          t0: bal,
          t1: regrip ?? urEnd,
          weigh: true,
        });
      stages.push({
        lane: "ur",
        label: "UR5e · Balance → OT-2 slot 2",
        t0: regrip ?? bal ?? urStart,
        t1: otClear ?? urEnd,
        blocked: !reached,
      });
    }
    const syn = prep.O.ops.find((o) => o.label === W.SYNTHESIS);
    stages.push(
      syn
        ? { lane: "ot2", ...syn }
        : {
            lane: "ot2",
            label: W.SYNTHESIS,
            t0: total - 2,
            t1: total - 2,
            blocked: true,
          },
    );
    stages.sort((x, y) => x.t0 - y.t0);
    let flowMsg: Compiled["flowMsg"];
    if (!reached)
      flowMsg = {
        level: "bad",
        text: arm.states.some((s) => s.loc === "ot2-rotated")
          ? "The rack reached OT-2 slot 2 turned 180°. Synthesis waits until the vials are where the OT-2 protocol expects them."
          : "The rack never reaches OT-2 slot 2, so synthesis cannot start. Check the arm chain.",
      };
    else if (hits.length)
      flowMsg = {
        level: "bad",
        text: "The arm path enters a keep-out. See the arm chain.",
      };
    else
      flowMsg = {
        level: "ok",
        text: `Complete run: ${Math.round(total)} s of workcell time. The rack is weighed and reaches OT-2 slot 2 the right way round.`,
      };
    this.wf = {
      prep,
      plan,
      urStart,
      arrive,
      leave,
      grips,
      rackTimeline,
      arm,
      events,
      total,
      stages,
      planMsg,
      flowMsg,
      hits,
      release,
      regrip,
      log: [],
    };
    this.wf.log = this.buildLog();
    S.t = Math.min(S.t, total);
    this.rebuildMarkers();
    this.emitChart(true);
  }
  private gripAtFrom(grips: Compiled["grips"], T: number) {
    let th = THETA_OPEN;
    for (const g of grips) {
      if (T >= g.t1) th = g.to;
      else if (T > g.t0) {
        th = g.from + ((g.to - g.from) * (T - g.t0)) / (g.t1 - g.t0);
        break;
      } else break;
    }
    return th;
  }
  private buildTrails(plan: K.Plan, arrive: number[]) {
    this.trailGroup.clear();
    this.trails = [];
    this.trailDots = [];
    const pts: number[][] = [[], [], [], [], []];
    const centre = (F: K.Mat4[], j: number) => {
      const c = HOUSING_CENTRE[j];
      return [
        F[j][0][3] + F[j][0][2] * c,
        F[j][1][3] + F[j][1][2] * c,
        F[j][2][3] + F[j][2][2] * c,
      ];
    };
    for (let t = 0; t <= plan.total + 1e-9; t += SAMPLE_DT) {
      const F = K.frames(
        K.sample(plan.segs, t).map((v) => v * DEG),
        C.TCP,
      );
      for (let j = 1; j <= 5; j++) pts[j - 1].push(...centre(F, j));
    }
    const { width, height } = this.host.getBoundingClientRect();
    pts.forEach((p, k) => {
      const g = new LineGeometry();
      g.setPositions(p);
      const material = new LineMaterial({
        color: new THREE.Color(this.css(`--j${k + 2}`)),
        linewidth: 2.4,
        transparent: true,
        opacity: 0.5,
        depthWrite: false,
      });
      material.resolution.set(width, height);
      const line = new Line2(g, material);
      line.renderOrder = 3;
      this.trailGroup.add(line);
      this.trails.push(line);
    });
    const dotGeo = new THREE.SphereGeometry(0.0065, 12, 8),
      haloGeo = new THREE.SphereGeometry(0.015, 12, 8);
    this.S.chain.forEach((w, i) => {
      const F = K.frames(
          w.degrees.map((v) => v * DEG),
          C.TCP,
        ),
        set: THREE.Mesh[] = [];
      for (let j = 1; j <= 5; j++) {
        const color = new THREE.Color(this.css(`--j${j + 1}`)),
          p = centre(F, j);
        const d = new THREE.Mesh(
          dotGeo,
          new THREE.MeshBasicMaterial({
            color,
            transparent: true,
            opacity: 0.85,
          }),
        );
        const h = new THREE.Mesh(
          haloGeo,
          new THREE.MeshBasicMaterial({
            color,
            transparent: true,
            opacity: 0.2,
            depthWrite: false,
          }),
        );
        d.position.set(p[0], p[1], p[2]);
        h.position.copy(d.position);
        this.trailGroup.add(d, h);
        set.push(d, h);
      }
      this.trailDots.push({ t: arrive[i], set });
    });
    this.trailGroup.visible = this.toggles.trails;
  }
  private revealTrails(u: number, pop = -1, popScale = 1) {
    const n =
      u === Infinity ? Infinity : Math.max(0, Math.floor(u / SAMPLE_DT));
    for (const l of [...this.trails, this.pathLine]) {
      if (!l) continue;
      const max =
        (
          l.geometry.attributes.instanceStart as
            THREE.InterleavedBufferAttribute | undefined
        )?.count ?? 0;
      l.geometry.instanceCount = Math.min(max, n);
    }
    this.trailDots.forEach((d, i) =>
      d.set.forEach((o) => {
        o.visible = d.t <= u + 1e-6;
        o.scale.setScalar(i === pop ? Math.max(0.01, popScale) : 1);
      }),
    );
    this.markers.children.forEach((o, k) => {
      const d = this.trailDots[Math.floor(k / 2)];
      o.visible = !!d && d.t <= u + 1e-6;
    });
  }
  private rebuildMarkers() {
    this.markers.clear();
    const accent = new THREE.Color(this.css("--accent")),
      info = new THREE.Color(this.css("--info"));
    const g1 = new THREE.SphereGeometry(0.008, 14, 10),
      g2 = new THREE.SphereGeometry(0.017, 14, 10);
    this.S.chain.forEach((w, i) => {
      const p = new THREE.Vector3().setFromMatrixPosition(tcpM(w.degrees)),
        sel = i === this.S.sel,
        color = sel ? accent : info;
      const m = new THREE.Mesh(g1, new THREE.MeshBasicMaterial({ color }));
      const h = new THREE.Mesh(
        g2,
        new THREE.MeshBasicMaterial({
          color,
          transparent: true,
          opacity: sel ? 0.35 : 0.16,
          depthWrite: false,
        }),
      );
      m.position.copy(p);
      h.position.copy(p);
      if (sel) (m.scale.setScalar(1.5), h.scale.setScalar(1.5));
      this.markers.add(m, h);
    });
    this.markers.visible = this.toggles.path;
  }
  private buildLog(): LogEntry[] {
    const wf = this.wf,
      L: LogEntry[] = [];
    for (const s of wf.stages)
      L.push({
        t: s.t0,
        dev: s.lane,
        text: `${s.blocked ? "Blocked: " : "Start: "}${s.label.split(" · ")[1]}`,
      });
    for (const e of wf.events) {
      if (e.type === "tipPick")
        L.push({ t: e.t, dev: e.dev, text: `Pick up tip ${e.well}` });
      else if (e.type === "tipDrop")
        L.push({ t: e.t, dev: e.dev, text: "Drop tip in trash" });
      else if (e.type === "mix")
        L.push({
          t: e.t,
          dev: e.dev,
          text: `Mix ${WELL_NAME(e.well)} ×${e.n}`,
        });
      else
        L.push({
          t: e.t0,
          dev: e.dev,
          text: e.to.startsWith("tip:")
            ? `Aspirate ${e.vol} µL from ${WELL_NAME(e.from)}`
            : `Dispense ${e.vol} µL into ${WELL_NAME(e.to)}`,
        });
    }
    if (wf.plan) {
      this.S.chain.forEach((w, i) => {
        const t = wf.arrive[i],
          loc = wf.arm.states[i].loc;
        L.push({
          t,
          dev: "ur",
          text: `Reached ${i + 1}/${this.S.chain.length} ${w.name}`,
        });
        if (w.grip === "close")
          L.push({
            t: t + 0.6,
            dev: "ur",
            text:
              loc === "arm"
                ? "Gripper closed on the sample rack"
                : "Gripper closed on nothing",
          });
        if (w.grip === "open")
          L.push({
            t: t + 0.25,
            dev: "ur",
            text: `Rack released · ${LOC[loc] ?? loc}`,
          });
      });
      const b = wf.release.balance;
      if (b !== undefined) {
        const g =
          W.RACK_TARE_G +
          this.rackMass(W.liquidState(wf.events, b + 2.5).wells);
        L.push({ t: b + 0.3, dev: "bal", text: "Load detected, settling" });
        L.push({
          t: b + 2.4,
          dev: "bal",
          text: `Stable ${g.toFixed(3)} g · net samples ${(g - W.RACK_TARE_G).toFixed(3)} g`,
        });
      }
    }
    L.push({ t: wf.total - 1, dev: "cell", text: wf.flowMsg.text });
    return L.sort((x, y) => x.t - y.t);
  }
  private rackMass(wells: Map<string, W.Comp>) {
    return W.VIALS.reduce(
      (m, v) => m + W.massG(wells.get(`rack:${v}`) ?? {}),
      0,
    );
  }

  // ---------- State at a time ----------
  private armDegAt(T: number) {
    const p = this.wf.plan;
    if (!p) return C.HOME;
    const u = T - this.wf.urStart;
    return u <= 0 ? C.HOME : K.sample(p.segs, Math.min(u, p.total));
  }
  private balanceAt(T: number, wells: Map<string, W.Comp>) {
    const r = this.wf.release.balance;
    if (r === undefined || T < r)
      return { text: "0.000", stable: true, note: "g · empty pan" };
    if (T >= (this.wf.regrip ?? Infinity))
      return { text: "0.000", stable: true, note: "g · rack removed" };
    const target = W.RACK_TARE_G + this.rackMass(wells),
      dt = T - r;
    const settle = Math.exp(-dt / 0.55),
      wob =
        Math.sin(dt * 23) * 0.9 * settle + Math.sin(dt * 7.3) * 0.12 * settle;
    const stable = dt > 2.4,
      v = target * (1 - Math.exp(-dt / 0.18)) + wob;
    return {
      text: (stable ? target : v).toFixed(3),
      stable,
      note: stable
        ? `g · net samples ${(target - W.RACK_TARE_G).toFixed(3)} g`
        : "g · settling",
    };
  }
  private snapshotCache: Snapshot | null = null;
  private renderWorld() {
    if (!this.wf) return;
    const S = this.S,
      wf = this.wf,
      T = S.t;
    const L = W.liquidState(wf.events, T);
    for (const [k, comp] of L.wells)
      this.liquids.set(k, W.total(comp), W.colour(comp));
    this.setFlexNozzle(W.gantryAt(wf.prep.F.segs, T, FLEX_PARK));
    for (const [n, node] of this.flexTips)
      node.visible = !L.used.has(`flex:tips:${n}`);
    const fOn = L.tips.flex,
      fVol = W.total(L.tipComp.flex);
    for (const n of this.flexPipTip)
      n.traverse((o) => {
        const m = o as THREE.Mesh;
        if (m.isMesh) {
          (m.material as THREE.MeshStandardMaterial).opacity = fOn ? 0.92 : 0;
          m.visible = fOn;
        }
      });
    for (const n of this.flexPipLiq)
      n.traverse((o) => {
        const m = o as THREE.Mesh;
        if (m.isMesh) {
          m.visible = fOn && fVol > 1;
          const mat = m.material as THREE.MeshStandardMaterial;
          mat.opacity = 0.9;
          if (fVol > 1) mat.color.setRGB(...W.colour(L.tipComp.flex));
        }
      });
    this.ot2.setNozzle(W.gantryAt(wf.prep.O.segs, T, this.ot2.park));
    this.ot2.setTip(
      L.tips.ot2,
      W.total(L.tipComp.ot2),
      W.colour(L.tipComp.ot2),
    );
    this.ot2Tips.resetTips();
    for (const k of L.used)
      if (k.startsWith("ot2:tips:")) this.ot2Tips.hideTip(k.slice(9));
    const editing = S.mode === "editor";
    const deg = editing ? S.pose : this.armDegAt(T);
    const theta = editing
      ? S.gripClosed
        ? THETA_RACK
        : THETA_OPEN
      : this.gripAtFrom(wf.grips, T);
    const tool = this.robot.pose(
      deg.map((v) => v * DEG),
      theta,
    );
    const tcp = tool
      .clone()
      .multiply(new THREE.Matrix4().makeTranslation(0, 0, C.TCP));
    let rackM: THREE.Matrix4, rackLoc: string;
    if (editing && S.sel >= 0 && wf.arm.states[S.sel]) {
      const st = wf.arm.states[S.sel];
      if (st.loc === "arm") {
        rackM = (
          S.gripClosed ? tcp.clone() : tcpM(S.chain[S.sel].degrees)
        ).multiply(st.offset!);
        rackLoc = S.gripClosed ? "arm" : "air";
      } else ((rackM = st.M), (rackLoc = st.loc));
    } else {
      const e = wf.rackTimeline.filter((x) => T >= x.t).at(-1)!;
      if (e.kind === "attach")
        ((rackM = tcp.clone().multiply(e.offset)), (rackLoc = "arm"));
      else ((rackM = e.M), (rackLoc = e.loc));
    }
    this.rack.matrix.copy(rackM);
    this.rack.matrixWorldNeedsUpdate = true;
    const B = this.balanceAt(T, L.wells);
    this.balance.setReading(B.text, B.stable);
    this.ring.visible = this.ringHit.visible = editing;
    if (editing) this.placeRing(deg);
    if (!this.D.active) this.revealTrails(Infinity);
    // Snapshot for the panels
    const tp = new THREE.Vector3().setFromMatrixPosition(tcp),
      hits = C.clearance(deg.map((v) => v * DEG));
    const urIdx = wf.plan ? wf.arrive.findIndex((x) => T <= x + 1e-6) : -1;
    const op = (ops: W.Op[]) =>
      ops.find((o) => T >= o.t0 && T < o.t1)?.label.split(" · ")[1] ?? null;
    const syn = wf.prep.O.ops.find((o) => o.label === W.SYNTHESIS);
    const stages = wf.stages.map((s) => {
      const [dev] = s.label.split(" · ");
      let sub = dev;
      if (s.weigh)
        sub = `Balance · ${(W.RACK_TARE_G + this.rackMass(W.liquidState(wf.events, s.t1 - 0.01).wells)).toFixed(3)} g gross`;
      if (s.blocked) sub = `${dev} · blocked`;
      return {
        ...s,
        sub,
        status: (s.blocked
          ? "blocked"
          : T >= s.t1
            ? "done"
            : T >= s.t0
              ? "now"
              : "pending") as Snapshot["stages"][number]["status"],
      };
    });
    const D = this.D;
    const design = D.active ? D.designLog.filter((e) => e.at <= D.tau) : [];
    const run =
      D.active && D.tau < D.runStart
        ? []
        : wf.log
            .filter((e) => e.t <= T + 1e-6)
            .map((e) => ({ ...e, stamp: `${e.t.toFixed(1)} s` }));
    const issues = wf.arm.issues;
    this.snapshotCache = {
      t: T,
      total: wf.total,
      playing: S.playing,
      editing,
      demo: {
        active: D.active,
        playing: D.playing,
        title: D.title,
        sub: D.sub,
      },
      joint: S.joint,
      pose: deg.slice(),
      gripClosed: editing
        ? S.gripClosed
        : theta > (THETA_OPEN + THETA_RACK) / 2,
      canUndo: S.undo.length > 0,
      sel: S.sel,
      visible: D.active ? D.visible : S.chain.length,
      current: S.mode === "playback" ? urIdx : -1,
      speed: S.speed,
      chain: S.chain.map((w, i) => ({
        ...w,
        travel: wf.plan ? wf.plan.rows[i].duration : null,
        issues: issues[i] ?? [],
      })),
      plan: wf.plan
        ? {
            total: wf.plan.total,
            peakV: wf.plan.peakV,
            hitSeconds: wf.hits.length * SAMPLE_DT,
          }
        : null,
      planMsg:
        wf.planMsg ??
        (issues.flat().length
          ? { level: "warn", text: "Some waypoints have notes; see the cards." }
          : {
              level: "ok",
              text: "Arm, fingers and rack clear every modelled keep-out.",
            }),
      flowMsg: wf.flowMsg,
      stages,
      log: [...design, ...run].slice(-220),
      balance: B,
      devices: {
        flex:
          op(wf.prep.F.ops) ??
          (T < (wf.prep.F.ops.at(-1)?.t1 ?? 0) ? "Moving" : "Done, parked"),
        ot2:
          op(wf.prep.O.ops) ??
          (syn && T >= syn.t1 ? "Done, parked" : "Waiting for the sample rack"),
        ur: !wf.plan
          ? "No valid plan"
          : T < wf.urStart
            ? "Waiting for sample preparation"
            : urIdx >= 0
              ? `→ ${S.chain[urIdx].name}`
              : "Home",
      },
      rack: LOC[rackLoc] ?? rackLoc,
      vials: W.VIALS.map((v) => {
        const c = L.wells.get(`rack:${v}`) ?? {};
        const sub = (Object.keys(c) as W.LiquidKey[]).find((k) =>
          /^s\d$/.test(k),
        );
        return {
          well: v,
          total: W.total(c),
          solvent: c.solvent ?? 0,
          substrate: sub ? (c[sub] ?? 0) : 0,
          reagent: c.reagent ?? 0,
          catalyst: c.catalyst ?? 0,
          mg: W.massG(c) * 1000,
          rgb: W.colour(c),
        };
      }),
      status:
        `TCP x ${(tp.x * 1000).toFixed(0)} · y ${(tp.y * 1000).toFixed(0)} · z ${(tp.z * 1000).toFixed(0)} mm` +
        (hits.length
          ? ` · ${hits[0].link} in ${hits[0].owner} ${hits[0].part}`
          : "") +
        (editing && !D.active ? " · editing" : ""),
      toggles: { ...this.toggles },
      message: this.message,
    };
  }
  private emit(force = false) {
    const now = performance.now();
    if (!force && now - this.lastEmit < 90) return;
    this.lastEmit = now;
    if (this.snapshotCache) this.onChange(this.snapshotCache);
    this.emitChart();
  }
  private emitChart(force = false) {
    const p = this.wf?.plan;
    if (!p)
      return this.onChart({
        total: 0,
        samples: [],
        arrive: [],
        hits: [],
        cursor: null,
      });
    if (force || !this.chartSamples) {
      this.chartSamples = [];
      for (let t = 0; t <= p.total; t += p.total / 400)
        this.chartSamples.push([t, K.sample(p.segs, t)]);
    }
    const u = this.S.t - this.wf.urStart;
    this.onChart({
      total: p.total,
      samples: this.chartSamples,
      arrive: this.wf.arrive.map((x) => x - this.wf.urStart),
      hits: this.wf.hits,
      cursor: this.S.mode === "playback" && u >= 0 && u <= p.total ? u : null,
    });
  }
  private chartSamples: [number, number[]][] | null = null;
  private update(force = true) {
    this.renderWorld();
    this.emit(force);
  }

  // ---------- Ring gizmo ----------
  private placeRing(deg: number[]) {
    const F = K.frames(
        deg.map((v) => v * DEG),
        C.TCP,
      ),
      j = this.S.joint;
    const o = new THREE.Vector3(F[j][0][3], F[j][1][3], F[j][2][3]),
      z = new THREE.Vector3(F[j][0][2], F[j][1][2], F[j][2][2]).normalize();
    const c = o.clone().addScaledVector(z, j === 0 ? 0.06 : HOUSING_CENTRE[j]);
    const r = [0.12, 0.11, 0.1, 0.08, 0.08, 0.08][j];
    for (const m of [this.ring, this.ringHit]) {
      m.position.copy(c);
      m.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), z);
      m.scale.setScalar(r / 0.1);
    }
    this.ringInfo = { c, z };
  }
  private ray = new THREE.Raycaster();
  private rayFrom(e: PointerEvent) {
    const r = this.renderer.domElement.getBoundingClientRect();
    this.ray.setFromCamera(
      new THREE.Vector2(
        ((e.clientX - r.left) / r.width) * 2 - 1,
        -((e.clientY - r.top) / r.height) * 2 + 1,
      ),
      this.camera,
    );
  }
  private planeAngle(e: PointerEvent) {
    this.rayFrom(e);
    const cw = this.ringInfo.c.clone().applyMatrix4(this.root.matrixWorld),
      zw = this.ringInfo.z.clone().transformDirection(this.root.matrixWorld);
    const hit = new THREE.Vector3();
    if (
      !this.ray.ray.intersectPlane(
        new THREE.Plane().setFromNormalAndCoplanarPoint(zw, cw),
        hit,
      )
    )
      return null;
    const u = hit.sub(cw),
      ax =
        Math.abs(zw.y) < 0.9
          ? new THREE.Vector3(0, 1, 0)
          : new THREE.Vector3(1, 0, 0);
    const b1 = ax.sub(zw.clone().multiplyScalar(ax.dot(zw))).normalize(),
      b2 = zw.clone().cross(b1);
    return Math.atan2(u.dot(b2), u.dot(b1));
  }
  private pointerDown = (e: PointerEvent) => {
    if (this.S.mode !== "editor" || this.D.active) return;
    this.rayFrom(e);
    if (!this.ray.intersectObject(this.ringHit).length) return;
    const a = this.planeAngle(e);
    if (a === null) return;
    this.beginEdit();
    this.drag = { a, start: this.S.pose[this.S.joint] };
    this.controls.enabled = false;
    this.renderer.domElement.setPointerCapture(e.pointerId);
  };
  private pointerMove = (e: PointerEvent) => {
    if (!this.drag) {
      if (this.S.mode === "editor") {
        this.rayFrom(e);
        this.renderer.domElement.style.cursor = this.ray.intersectObject(
          this.ringHit,
        ).length
          ? "grab"
          : "";
      }
      return;
    }
    const a = this.planeAngle(e);
    if (a === null) return;
    let d = a - this.drag.a;
    d = Math.atan2(Math.sin(d), Math.cos(d));
    this.drag.a = a;
    const lim = K.LIMIT_DEG[this.S.joint] - 0.1,
      j = this.S.joint;
    this.S.pose[j] = +Math.max(
      -lim,
      Math.min(lim, this.S.pose[j] + (d / DEG) * (e.shiftKey ? 0.2 : 1)),
    ).toFixed(2);
    this.update();
  };
  private endDrag = () => {
    if (this.drag) {
      this.drag = null;
      this.controls.enabled = true;
    }
  };
  private keyDown = (e: KeyboardEvent) => {
    if (e.key === "Escape" && this.drag) {
      this.S.pose[this.S.joint] = this.drag.start;
      this.endDrag();
      this.update();
    }
  };

  // ---------- Loop ----------
  private resize() {
    const { width, height } = this.host.getBoundingClientRect();
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / Math.max(1, height);
    this.camera.updateProjectionMatrix();
    this.pathMat.resolution.set(width, height);
    this.trails.forEach((l) => l.material.resolution.set(width, height));
  }
  private updateLabels() {
    const r = this.host.getBoundingClientRect(),
      p = new THREE.Vector3();
    for (const l of this.labels) {
      p.copy(l.pos).applyMatrix4(this.root.matrixWorld).project(this.camera);
      l.el.style.left = `${((p.x + 1) / 2) * r.width}px`;
      l.el.style.top = `${((1 - p.y) / 2) * r.height}px`;
      l.el.hidden = p.z > 1;
    }
  }
  private tick = (now: number) => {
    if (this.disposed || this.frozen) return;
    const dt = Math.min(0.1, (now - this.last) / 1000);
    this.last = now;
    if (this.D.playing) {
      this.D.tau += dt;
      if (this.D.tau >= this.D.duration) {
        this.D.tau = this.D.duration;
        this.D.playing = false;
      }
      this.demoApply(this.D.tau);
    } else if (this.S.playing) {
      this.S.t += dt * this.S.rate;
      if (this.S.t >= this.wf.total) {
        this.S.t = this.wf.total;
        this.S.playing = false;
      }
      this.update(false);
    }
    if (!this.D.active) this.controls.update();
    this.renderer.render(this.scene, this.camera);
    this.updateLabels();
    this.raf = requestAnimationFrame(this.tick);
  };
  private applyTheme = () => {
    this.benchMat.color.set(this.css("--surface-2"));
    (this.benchEdge.material as THREE.LineBasicMaterial).color.set(
      this.css("--line-strong"),
    );
    this.ringMat.color.set(this.css("--accent"));
    this.keepMat.color.set(this.css("--danger"));
    this.keepEdge.color.set(this.css("--danger"));
    this.compile();
    this.update();
  };

  // ---------- Demo ----------
  private setupDemo() {
    const S = this.S,
      D = this.D;
    S.chain = C.generateTransfer(this.stations);
    S.sel = -1;
    S.speed = 30;
    this.compile();
    const N = S.chain.length,
      plan = this.wf.plan!;
    D.designStart = D.intro;
    D.designEnd = D.intro + N * D.step;
    D.runStart = D.designEnd + D.validate;
    const urS = this.wf.urStart,
      urE = urS + plan.total;
    D.map = [];
    let tau = 0;
    for (const [T0, T1, rate] of [
      [0, urS - 4, 16],
      [urS - 4, urE, 2.4],
      [urE, this.wf.total, 16],
    ]) {
      D.map.push({ T0, T1, rate, tau0: tau });
      tau += (T1 - T0) / rate;
    }
    D.runEnd = D.runStart + tau;
    D.duration = D.runEnd + D.outro;
    D.how = S.chain.map((w) =>
      /^Above|^Grip|^Set|^Place|^Regrip/.test(w.name)
        ? "Move tool to · nominal IK"
        : /^Return home/.test(w.name)
          ? "Home pose"
          : /^Front of|^Back out/.test(w.name)
            ? "Move tool to · approach point"
            : "Jog tool · 1 cm steps",
    );
    D.designLog = [
      {
        at: 0.3,
        t: 0,
        stamp: "design",
        dev: "design",
        text: `Design the UR5e path: ${N} waypoints from Flex D2 via the balance to OT-2 slot 2`,
      },
    ];
    S.chain.forEach((w, i) =>
      D.designLog.push({
        at: D.designStart + (i + 0.7) * D.step,
        t: 0,
        stamp: `#${String(i + 1).padStart(2, "0")}`,
        dev: "design",
        text: `Recorded ${w.name} · ${w.degrees.map((v) => (+v).toFixed(0)).join(" / ")}°${w.grip ? ` · ${w.grip} gripper` : ""}${w.hold ? ` · hold ${w.hold} s` : ""}`,
      }),
    );
    D.designLog.push({
      at: D.designEnd + 0.4,
      t: 0,
      stamp: "check",
      dev: "design",
      text: `Validated ${N} waypoints · ${plan.total.toFixed(1)} s at ${S.speed} °/s · peak ${plan.peakV.toFixed(1)} °/s · ${this.wf.hits.length ? `${(this.wf.hits.length * SAMPLE_DT).toFixed(2)} s in keep-outs` : "no clearance hits"}`,
    });
    const T2 = (T: number) => {
      const s = D.map.find((x) => T <= x.T1) ?? D.map[D.map.length - 1];
      return D.runStart + s.tau0 + (T - s.T0) / s.rate;
    };
    const r = this.wf.release;
    D.cams = [
      { tau: 0, v: "design" },
      { tau: D.runStart, v: "cell" },
      { tau: T2(12), v: "flex" },
      { tau: T2(150), v: "ot2run" },
      { tau: T2(urS - 6), v: "cell" },
      { tau: T2((r.balance ?? urS) - 3), v: "balance" },
      { tau: T2((this.wf.regrip ?? urS) + 1), v: "cell" },
      { tau: T2((r.ot2 ?? urE) - 6), v: "ot2run" },
      { tau: D.runEnd - 2, v: "cell" },
    ];
  }
  private tauToT(tau: number) {
    const D = this.D,
      u = tau - D.runStart;
    let s = D.map[0];
    for (const x of D.map) if (u >= x.tau0) s = x;
    return Math.min(this.wf.total, s.T0 + (u - s.tau0) * s.rate);
  }
  private demoCamera(tau: number) {
    const c = this.D.cams;
    let k = 0;
    for (let i = 0; i < c.length; i++) if (tau >= c[i].tau) k = i;
    const to = VIEWS[c[k].v],
      from = VIEWS[c[Math.max(0, k - 1)].v],
      e = k ? smooth((tau - c[k].tau) / 1.8) : 1;
    const pos = to.pos.map(
        (v, i) => from.pos[i] + (v - from.pos[i]) * e,
      ) as C.Vec3,
      tgt = to.target.map(
        (v, i) => from.target[i] + (v - from.target[i]) * e,
      ) as C.Vec3;
    this.camera.position.set(...pos);
    this.controls.target.set(...tgt);
    this.camera.lookAt(...tgt);
  }
  private demoApply(tau: number) {
    const D = this.D,
      S = this.S,
      N = S.chain.length;
    D.active = true;
    D.tau = tau;
    if (tau < D.runStart) {
      S.mode = "editor";
      S.t = 0;
      S.playing = false;
      let rec = 0,
        pose = C.HOME,
        pop = -1,
        popScale = 1;
      if (tau >= D.designStart && tau < D.designEnd) {
        const x = (tau - D.designStart) / D.step,
          i = Math.floor(x),
          f = x - i;
        const a = i ? S.chain[i - 1].degrees : C.HOME,
          b = S.chain[i].degrees,
          e = smooth(f / 0.62);
        pose = a.map((v, j) => v + (b[j] - v) * e);
        rec = f >= 0.7 ? i + 1 : i;
        if (f >= 0.7)
          ((pop = i), (popScale = 0.4 + 0.6 * smooth((f - 0.7) / 0.15)));
        let jmax = 0;
        b.forEach((v, j) => {
          if (Math.abs(v - a[j]) > Math.abs(b[jmax] - a[jmax])) jmax = j;
        });
        S.joint = jmax;
        D.title = `1 · Design the arm path — waypoint ${i + 1} of ${N}`;
        D.sub = `${S.chain[i].name} · ${D.how[i]}${S.chain[i].grip ? ` · ${S.chain[i].grip} gripper` : ""}`;
      } else if (tau >= D.designEnd) {
        rec = N;
        pose = S.chain[N - 1].degrees;
        D.title = "Arm path validated";
        D.sub = `${N} waypoints · ${this.wf.plan!.total.toFixed(1)} s · each joint keeps its own trace`;
      } else {
        D.title = "1 · Design the arm path";
        D.sub = "Record UR5e waypoints; every joint leaves a coloured trace";
      }
      D.visible = rec;
      S.pose = pose.slice();
      S.sel = rec - 1;
      S.gripClosed = rec ? this.wf.arm.states[rec - 1].loc === "arm" : false;
      this.renderWorld();
      this.revealTrails(
        rec ? this.wf.arrive[rec - 1] - this.wf.urStart : -1,
        pop,
        popScale,
      );
    } else {
      D.visible = N;
      S.mode = "playback";
      S.sel = -1;
      S.t = tau >= D.runEnd ? this.wf.total : this.tauToT(tau);
      const now = this.wf.stages
        .filter((s) => S.t >= s.t0 && S.t < s.t1)
        .map((s) => s.label);
      D.title = tau >= D.runEnd ? "Run complete" : "2 · Run the workflow";
      D.sub =
        tau >= D.runEnd
          ? this.wf.flowMsg.text
          : now.length
            ? now.join("  ·  ")
            : "Instruments idle";
      this.renderWorld();
      this.revealTrails(Infinity);
    }
    this.demoCamera(tau);
    this.emit(!D.playing);
  }

  // ---------- Public API ----------
  startDemo() {
    this.S.playing = false;
    this.setupDemo();
    this.D.active = true;
    this.D.playing = true;
    this.D.tau = 0;
    this.last = performance.now();
  }
  stopDemo() {
    if (!this.D.active) return;
    this.D.active = false;
    this.D.playing = false;
    this.persist();
    this.update();
  }
  /** Deterministic demo frames for recording: seek and render synchronously. */
  demoFrames() {
    this.frozen = true;
    this.setupDemo();
    this.D.active = true;
    return {
      duration: this.D.duration,
      seek: (tau: number) => {
        this.demoApply(tau);
        this.renderer.render(this.scene, this.camera);
        this.updateLabels();
      },
    };
  }
  setView(v: View) {
    const p = VIEWS[v];
    this.camera.position.set(...p.pos);
    this.controls.target.set(...p.target);
    this.controls.update();
  }
  togglePlay() {
    this.stopDemo();
    if (!this.S.playing && this.S.t >= this.wf.total - 0.01) this.S.t = 0;
    this.S.mode = "playback";
    this.S.playing = !this.S.playing;
    this.last = performance.now();
    this.update();
  }
  setRate(r: number) {
    this.S.rate = r;
  }
  seek(t: number) {
    this.stopDemo();
    this.S.mode = "playback";
    this.S.playing = false;
    this.S.t = Math.max(0, Math.min(this.wf.total, t));
    this.update();
  }
  seekArm(u: number) {
    if (this.wf.plan) this.seek(this.wf.urStart + u);
  }
  toggle(k: "trails" | "path" | "keepouts") {
    this.toggles[k] = !this.toggles[k];
    if (this.pathLine) this.pathLine.visible = this.toggles.path;
    this.markers.visible = this.toggles.path;
    this.trailGroup.visible = this.toggles.trails;
    this.keepGroup.visible = this.toggles.keepouts;
    this.update();
  }
  private beginEdit() {
    this.stopDemo();
    const S = this.S;
    if (S.mode !== "editor") {
      S.pose = this.armDegAt(S.t).map((v) => +v.toFixed(2));
      S.gripClosed =
        this.gripAtFrom(this.wf.grips, S.t) > (THETA_OPEN + THETA_RACK) / 2;
      S.mode = "editor";
      S.playing = false;
    }
    S.undo.push(S.pose.slice());
    if (S.undo.length > 50) S.undo.shift();
  }
  selectJoint(j: number) {
    this.S.joint = j;
    this.update();
  }
  setJoint(j: number, value: number, continuing = false) {
    if (!continuing) this.beginEdit();
    const lim = K.LIMIT_DEG[j] - 0.1;
    this.S.joint = j;
    this.S.pose[j] = +Math.max(-lim, Math.min(lim, value)).toFixed(2);
    this.update();
  }
  undo() {
    const p = this.S.undo.pop();
    if (!p) return;
    this.S.mode = "editor";
    this.S.pose = p;
    this.update();
  }
  toggleGripper() {
    this.beginEdit();
    this.S.undo.pop();
    this.S.gripClosed = !this.S.gripClosed;
    this.update();
  }
  targets() {
    return [
      { label: "Home", run: () => C.HOME.slice() },
      ...Object.values(this.stations).flatMap((s) => {
        const up =
          s.base + C.RACK.grip + (s.id === "ot2" ? C.OT2_APPROACH : C.APPROACH);
        return [
          {
            label: `Above ${s.label}`,
            run: () => C.reach(s.x, s.y, up, this.S.pose),
          },
          {
            label: `Grip height at ${s.label}`,
            run: () => C.reach(s.x, s.y, s.base + C.RACK.grip, this.S.pose),
          },
        ];
      }),
    ];
  }
  moveTo(index: number) {
    const t = this.targets()[index];
    this.beginEdit();
    const q = t.run();
    if (!q) {
      this.S.undo.pop();
      return this.flash(
        `No nearby IK solution for “${t.label}” from this pose.`,
      );
    }
    this.S.pose = q;
    this.update();
  }
  jog(d: C.Vec3) {
    this.beginEdit();
    const S = this.S,
      f = K.fk(
        S.pose.map((v) => v * DEG),
        C.TCP,
      ),
      yaw = Math.atan2(f[1][0], f[0][0]);
    const r = K.ik(
      K.downPose(f[0][3] + d[0], f[1][3] + d[1], f[2][3] + d[2], yaw),
      S.pose.map((v) => v * DEG),
      C.TCP,
    );
    if (!r) {
      S.undo.pop();
      return this.flash("No nearby tool-down IK solution for that step.");
    }
    S.pose = r.q.map((v) => +(v / DEG).toFixed(2));
    this.update();
  }
  selectWaypoint(i: number) {
    this.stopDemo();
    const S = this.S,
      w = S.chain[i];
    S.sel = i;
    S.mode = "editor";
    S.playing = false;
    S.pose = w.degrees.slice();
    S.gripClosed = this.wf.arm.states[i]?.loc === "arm";
    if (this.wf.plan) S.t = this.wf.leave[i];
    this.rebuildMarkers();
    this.update();
  }
  private changed() {
    this.persist();
    this.compile();
    this.update();
  }
  addWaypoint(w: Omit<K.Waypoint, "degrees">) {
    const S = this.S;
    if (S.chain.length >= 24) return;
    const at = S.sel >= 0 ? S.sel + 1 : S.chain.length;
    S.chain.splice(at, 0, { ...w, degrees: S.pose.slice() });
    S.sel = at;
    this.changed();
  }
  updateWaypoint(w: Omit<K.Waypoint, "degrees">) {
    const S = this.S;
    if (S.sel < 0) return;
    S.chain[S.sel] = { ...w, degrees: S.pose.slice() };
    this.changed();
  }
  moveWaypoint(i: number, d: number) {
    const S = this.S,
      j = i + d;
    if (j < 0 || j >= S.chain.length) return;
    [S.chain[i], S.chain[j]] = [S.chain[j], S.chain[i]];
    S.sel = j;
    this.changed();
  }
  duplicateWaypoint(i: number) {
    this.S.chain.splice(i + 1, 0, structuredClone(this.S.chain[i]));
    this.S.sel = i + 1;
    this.changed();
  }
  deleteWaypoint(i: number) {
    this.S.chain.splice(i, 1);
    this.S.sel = Math.min(this.S.sel, this.S.chain.length - 1);
    this.changed();
  }
  regenerate() {
    this.stopDemo();
    this.S.chain = C.generateTransfer(this.stations);
    this.S.sel = -1;
    this.S.mode = "playback";
    this.changed();
  }
  clear() {
    this.S.chain = [];
    this.S.sel = -1;
    this.changed();
  }
  setSpeed(v: number) {
    this.S.speed = Math.max(1, Math.min(40, Math.round(v)));
    this.changed();
  }
  /** The planned arm motion as timed joint vectors (rad) with the keep-outs it must clear. */
  armPath(dt = 0.04) {
    const p = this.wf.plan;
    if (!p) return null;
    const n = Math.ceil(p.total / dt);
    return {
      arm: "ur5e",
      dt,
      joints: Array.from({ length: n + 1 }, (_, k) =>
        K.sample(p.segs, Math.min(k * dt, p.total)).map((v) => v * DEG),
      ),
      boxes: C.keepouts().map((b) => ({
        name: `${b.owner} ${b.part}`.slice(0, 80),
        min: b.min,
        max: b.max,
        stand: !!b.skipNearBase,
      })),
      tool_m: C.TCP,
    };
  }
  exportJSON() {
    const S = this.S;
    return JSON.stringify(
      {
        schema: "ur5e.action-chain/2",
        timing_mode: "automatic",
        units: "degrees",
        reference: C.HOME,
        speed: S.speed,
        waypoints: S.chain.map((w) => ({
          name: (w.grip ? `${w.name} [${w.grip} gripper]` : w.name).slice(
            0,
            60,
          ),
          degrees: w.degrees.map((v) => +(+v).toFixed(2)),
          hold: w.hold || 0,
        })),
      },
      null,
      1,
    );
  }
  importJSON(text: string) {
    try {
      const d = JSON.parse(text);
      if (d.schema !== "ur5e.action-chain/2" || !Array.isArray(d.waypoints))
        throw new Error(
          "Expected schema ur5e.action-chain/2 with a waypoints list.",
        );
      const chain: K.Waypoint[] = d.waypoints.map(
        (w: { name?: string; degrees: number[]; hold?: number }) => {
          if (
            !Array.isArray(w.degrees) ||
            w.degrees.length !== 6 ||
            !w.degrees.every(Number.isFinite)
          )
            throw new Error("Each waypoint needs six finite angles.");
          const m = /\s\[(close|open) gripper\]$/.exec(w.name || "");
          return {
            name: (w.name || "Waypoint").replace(
              /\s\[(close|open) gripper\]$/,
              "",
            ),
            degrees: w.degrees.slice(),
            hold: +(w.hold ?? 0) || 0,
            grip: (m ? m[1] : null) as K.Waypoint["grip"],
          };
        },
      );
      this.S.chain = chain;
      if (d.speed >= 1 && d.speed <= 40) this.S.speed = d.speed;
      this.S.sel = -1;
      this.changed();
      this.flash(
        `Loaded ${chain.length} waypoints. Importing never moves a robot.`,
        "ok",
      );
    } catch (e) {
      this.flash((e as Error).message, "bad");
    }
  }
  flash(text: string, level: Level = "bad") {
    this.message = { level, text };
    window.clearTimeout(this.messageTimer);
    this.messageTimer = window.setTimeout(() => {
      this.message = null;
      this.update();
    }, 4000);
    this.update();
  }
  private persist() {
    try {
      localStorage.setItem(
        STORE,
        JSON.stringify({ chain: this.S.chain, speed: this.S.speed }),
      );
    } catch {
      /* Storage may be unavailable; edits last for this page only. */
    }
  }
  dispose() {
    this.disposed = true;
    cancelAnimationFrame(this.raf);
    this.observer.disconnect();
    this.themeObserver.disconnect();
    this.media.removeEventListener("change", this.applyTheme);
    window.removeEventListener("keydown", this.keyDown);
    window.clearTimeout(this.messageTimer);
    this.controls.dispose();
    this.labels.forEach((l) => l.el.remove());
    this.scene.traverse((o) => {
      const m = o as THREE.Mesh;
      m.geometry?.dispose();
      const mat = m.material as THREE.Material | THREE.Material[] | undefined;
      (Array.isArray(mat) ? mat : mat ? [mat] : []).forEach((x) => x.dispose());
    });
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}
