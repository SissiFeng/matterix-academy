// OT-2 teaching model in the Opentrons deck frame (deck mm + cornerOffsetFromOrigin, metres, Z up,
// front toward -Y). Proportions follow published photos and the 63 × 57 × 66 cm envelope; not vendor CAD.
import * as THREE from "three";
import type { Deck, Vec3 } from "./cell";

const M = {
  alu: new THREE.MeshStandardMaterial({
    color: 0xc9ced4,
    metalness: 0.55,
    roughness: 0.35,
  }),
  aluDark: new THREE.MeshStandardMaterial({
    color: 0x8d949b,
    metalness: 0.5,
    roughness: 0.4,
  }),
  black: new THREE.MeshStandardMaterial({ color: 0x23262a, roughness: 0.55 }),
  graphite: new THREE.MeshStandardMaterial({ color: 0x3b4046, roughness: 0.5 }),
  white: new THREE.MeshStandardMaterial({ color: 0xf1f2f2, roughness: 0.45 }),
  grey: new THREE.MeshStandardMaterial({ color: 0xa9afb5, roughness: 0.5 }),
  smoke: new THREE.MeshPhysicalMaterial({
    color: 0x30363c,
    roughness: 0.1,
    transparent: true,
    opacity: 0.32,
    depthWrite: false,
    side: THREE.DoubleSide,
  }),
  acrylic: new THREE.MeshPhysicalMaterial({
    color: 0xdfeef6,
    roughness: 0.08,
    transparent: true,
    opacity: 0.16,
    depthWrite: false,
    side: THREE.DoubleSide,
  }),
  blue: new THREE.MeshStandardMaterial({
    color: 0x3a8ee6,
    emissive: 0x3a8ee6,
    emissiveIntensity: 0.9,
  }),
  rubber: new THREE.MeshStandardMaterial({ color: 0x15171a, roughness: 0.9 }),
  tip: new THREE.MeshStandardMaterial({
    color: 0xf6f7f8,
    roughness: 0.35,
    transparent: true,
    opacity: 0.9,
  }),
};
function box(
  w: number,
  d: number,
  h: number,
  m: THREE.Material,
  x: number,
  y: number,
  z: number,
  parent: THREE.Object3D,
) {
  const o = new THREE.Mesh(new THREE.BoxGeometry(w, d, h), m);
  o.position.set(x, y, z);
  parent.add(o);
  return o;
}
function rbox(
  w: number,
  d: number,
  h: number,
  r: number,
  m: THREE.Material,
  x: number,
  y: number,
  z: number,
  parent: THREE.Object3D,
) {
  const s = new THREE.Shape();
  s.moveTo(-w / 2 + r, -d / 2);
  s.lineTo(w / 2 - r, -d / 2);
  s.quadraticCurveTo(w / 2, -d / 2, w / 2, -d / 2 + r);
  s.lineTo(w / 2, d / 2 - r);
  s.quadraticCurveTo(w / 2, d / 2, w / 2 - r, d / 2);
  s.lineTo(-w / 2 + r, d / 2);
  s.quadraticCurveTo(-w / 2, d / 2, -w / 2, d / 2 - r);
  s.lineTo(-w / 2, -d / 2 + r);
  s.quadraticCurveTo(-w / 2, -d / 2, -w / 2 + r, -d / 2);
  const g = new THREE.ExtrudeGeometry(s, {
    depth: h,
    bevelEnabled: false,
    curveSegments: 6,
  });
  g.translate(0, 0, -h / 2);
  const o = new THREE.Mesh(g, m);
  o.position.set(x, y, z);
  parent.add(o);
  return o;
}
const cylZ = (r1: number, r2: number, h: number, seg = 20) =>
  new THREE.CylinderGeometry(r1, r2, h, seg).rotateX(Math.PI / 2);

function deckTexture(deck: Deck) {
  const W = 1248,
    H = 1130,
    c = document.createElement("canvas");
  c.width = W;
  c.height = H;
  const x = c.getContext("2d")!,
    sx = W / 624.3,
    sy = H / 565.2;
  x.fillStyle = "#3d4248";
  x.fillRect(0, 0, W, H);
  const ox = -deck.corner[0],
    oy = -deck.corner[1];
  for (let i = 1; i <= 12; i++) {
    const p = deck.cutouts[`cutout${i}`];
    const X = (p[0] + ox) * sx,
      Y = H - (p[1] + oy + 85.48) * sy;
    x.fillStyle = i === 12 ? "#34383d" : "#4b5157";
    x.fillRect(X, Y, 127.76 * sx, 85.48 * sy);
    x.strokeStyle = "#6d747b";
    x.lineWidth = 3;
    x.strokeRect(X + 2, Y + 2, 127.76 * sx - 4, 85.48 * sy - 4);
    x.fillStyle = "#c9ced4";
    x.font = "600 34px system-ui, sans-serif";
    if (i < 12) x.fillText(String(i), X + 10, Y + 40);
  }
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 8;
  return t;
}

export type OT2 = {
  group: THREE.Group;
  setNozzle(N: Vec3): void;
  setTip(on: boolean, vol: number, rgb: Vec3): void;
  REACH: number;
  park: Vec3;
  trash: Vec3;
};

export function buildOT2(deck: Deck): OT2 {
  const g = new THREE.Group();
  const X0 = -0.12,
    X1 = 0.513,
    Y0 = -0.115,
    Y1 = 0.455,
    ZB = -0.1,
    ZT = 0.56;
  const W = X1 - X0,
    Dp = Y1 - Y0,
    cx = (X0 + X1) / 2,
    cy = (Y0 + Y1) / 2;
  rbox(W, Dp, 0.088, 0.012, M.graphite, cx, cy, ZB + 0.044, g);
  box(W - 0.02, 0.006, 0.05, M.black, cx, Y0 - 0.002, ZB + 0.045, g);
  box(0.012, 0.004, 0.012, M.blue, X1 - 0.05, Y0 - 0.0045, ZB + 0.05, g);
  for (const fx of [X0 + 0.04, X1 - 0.04])
    for (const fy of [Y0 + 0.04, Y1 - 0.04]) {
      const f = new THREE.Mesh(cylZ(0.016, 0.018, 0.012), M.rubber);
      f.position.set(fx, fy, ZB - 0.004);
      g.add(f);
    }
  const deckW = 0.6243,
    deckD = 0.5652;
  const dX = deck.corner[0] / 1000 + deckW / 2,
    dY = deck.corner[1] / 1000 + deckD / 2;
  box(deckW, deckD, 0.012, M.aluDark, dX, dY, -0.006, g);
  const top = new THREE.Mesh(
    new THREE.PlaneGeometry(deckW, deckD),
    new THREE.MeshStandardMaterial({
      map: deckTexture(deck),
      roughness: 0.6,
      metalness: 0.3,
    }),
  );
  top.position.set(dX, dY, 0.0004);
  g.add(top);
  const post = 0.026;
  for (const px of [X0 + post / 2, X1 - post / 2])
    for (const py of [Y0 + post / 2, Y1 - post / 2])
      box(post, post, ZT - ZB - 0.088, M.alu, px, py, (ZT + ZB + 0.088) / 2, g);
  box(W, post, post, M.alu, cx, Y0 + post / 2, ZT - post / 2, g);
  box(W, post, post, M.alu, cx, Y1 - post / 2, ZT - post / 2, g);
  box(post, Dp, post, M.alu, X0 + post / 2, cy, ZT - post / 2, g);
  box(post, Dp, post, M.alu, X1 - post / 2, cy, ZT - post / 2, g);
  box(W - 2 * post, 0.004, 0.04, M.black, cx, Y0 + 0.002, ZT - 0.02, g); // front header, 520–560 mm
  box(W - 2 * post, Dp - 2 * post, 0.004, M.smoke, cx, cy, ZT - 0.002, g); // tinted top panel
  box(0.004, Dp - post, ZT, M.acrylic, X0 + 0.003, cy, ZT / 2, g);
  box(0.004, Dp - post, ZT, M.acrylic, X1 - 0.003, cy, ZT / 2, g);
  box(W - post, 0.004, ZT, M.acrylic, cx, Y1 - 0.003, ZT / 2, g);
  // The front door is removed so the arm can reach slot 2. Fixed trash from the deck definition:
  const tc = deck.cutouts.cutout12,
    ta = deck.areas.fixedTrash;
  const tx = (tc[0] + ta.off[0] + deck.corner[0]) / 1000,
    ty = (tc[1] + ta.off[1] + deck.corner[1]) / 1000;
  const tw = ta.box.xDimension / 1000,
    td = ta.box.yDimension / 1000,
    th = ta.box.zDimension / 1000;
  const trash = new THREE.Group();
  trash.position.set(tx + tw / 2, ty + td / 2, 0);
  g.add(trash);
  const wt = 0.004;
  box(tw, wt, th, M.black, 0, -td / 2 + wt / 2, th / 2, trash);
  box(tw, wt, th, M.black, 0, td / 2 - wt / 2, th / 2, trash);
  box(wt, td, th, M.black, -tw / 2 + wt / 2, 0, th / 2, trash);
  box(wt, td, th, M.black, tw / 2 - wt / 2, 0, th / 2, trash);
  box(tw, td, 0.004, M.graphite, 0, 0, 0.002, trash);
  // Gantry: Y rails, X beam, carriage with two Z mounts, P300 single-channel on the right mount.
  const RZ = 0.4;
  box(0.03, Dp - 0.06, 0.03, M.black, X0 + 0.04, cy, RZ, g);
  box(0.03, Dp - 0.06, 0.03, M.black, X1 - 0.04, cy, RZ, g);
  const beam = new THREE.Group();
  g.add(beam);
  box(W - 0.08, 0.05, 0.04, M.graphite, cx, 0, RZ + 0.005, beam);
  box(0.05, 0.07, 0.05, M.black, X0 + 0.04, 0, RZ + 0.01, beam);
  box(0.05, 0.07, 0.05, M.black, X1 - 0.04, 0, RZ + 0.01, beam);
  const carriage = new THREE.Group();
  beam.add(carriage);
  rbox(0.1, 0.06, 0.11, 0.008, M.white, 0, -0.045, RZ - 0.01, carriage);
  box(0.09, 0.002, 0.08, M.grey, 0, -0.0755, RZ - 0.01, carriage);
  for (const s of [-1, 1])
    box(0.012, 0.012, 0.16, M.aluDark, s * 0.034, -0.082, RZ - 0.09, carriage);
  const pip = new THREE.Group();
  carriage.add(pip);
  rbox(0.034, 0.044, 0.15, 0.01, M.white, 0, 0, 0.115, pip);
  box(0.034, 0.044, 0.02, M.black, 0, 0, 0.198, pip);
  box(0.022, 0.0015, 0.05, M.grey, 0, -0.0225, 0.12, pip);
  box(0.03, 0.008, 0.2, M.aluDark, 0, 0.026, 0.2, pip);
  const shaft = new THREE.Mesh(cylZ(0.005, 0.0045, 0.03), M.grey);
  shaft.position.set(0, 0, 0.026);
  pip.add(shaft);
  const nozzle = new THREE.Mesh(cylZ(0.0028, 0.0022, 0.012), M.graphite);
  nozzle.position.set(0, 0, 0.006);
  pip.add(nozzle);
  const ej = new THREE.Mesh(cylZ(0.0018, 0.0018, 0.03), M.black);
  ej.position.set(0.012, 0, 0.03);
  pip.add(ej);
  const TIP_LEN = 0.0593,
    OVER = 0.00747,
    REACH = TIP_LEN - OVER;
  const tipGeo = cylZ(0.0029, 0.0005, TIP_LEN, 18);
  tipGeo.translate(0, 0, -TIP_LEN / 2 + OVER);
  const tip = new THREE.Mesh(tipGeo, M.tip);
  tip.visible = false;
  pip.add(tip);
  const tipLiq = new THREE.Mesh(
    cylZ(0.0018, 0.0006, 1, 12).translate(0, 0, 0.5),
    new THREE.MeshStandardMaterial({
      color: 0x4a90c2,
      transparent: true,
      opacity: 0.9,
    }),
  );
  tipLiq.position.z = -REACH + 0.002;
  tipLiq.visible = false;
  pip.add(tipLiq);
  const MOUNT = [0.034, -0.106];
  const setNozzle = (N: Vec3) => {
    beam.position.y = N[1] - MOUNT[1];
    carriage.position.x = N[0] - MOUNT[0];
    pip.position.set(MOUNT[0], MOUNT[1], N[2]);
  };
  const park: Vec3 = [cx, Y1 - 0.09, 0.22];
  setNozzle(park);
  return {
    group: g,
    setNozzle,
    setTip(on, vol, rgb) {
      tip.visible = on;
      tipLiq.visible = on && vol > 0.5;
      tipLiq.scale.z = Math.max(
        1e-4,
        Math.min(REACH * 0.8, (vol / 300) * REACH * 0.75),
      );
      (tipLiq.material as THREE.MeshStandardMaterial).color.setRGB(...rgb);
    },
    REACH,
    park,
    trash: [tx + tw / 2, ty + td / 2, th],
  };
}
