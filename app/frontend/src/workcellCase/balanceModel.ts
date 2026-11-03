// Generic top-loading precision balance (no brand): housing, steel pan, feet and a live display.
import * as THREE from "three";
import { BALANCE } from "./cell";

export function buildBalance() {
  const g = new THREE.Group();
  const [cx, cy] = BALANCE.centre,
    [W, Dp, H] = BALANCE.size;
  const shell = new THREE.MeshStandardMaterial({
    color: 0xe9ecee,
    roughness: 0.45,
    side: THREE.DoubleSide,
  });
  const dark = new THREE.MeshStandardMaterial({
    color: 0x2a2e33,
    roughness: 0.5,
  });
  const steel = new THREE.MeshStandardMaterial({
    color: 0xd5d9dd,
    metalness: 0.85,
    roughness: 0.22,
  });
  const add = (
    geo: THREE.BufferGeometry,
    m: THREE.Material,
    x: number,
    y: number,
    z: number,
  ) => {
    const o = new THREE.Mesh(geo, m);
    o.position.set(x, y, z);
    g.add(o);
    return o;
  };
  // Housing with a sloped front console: the profile lies in (y, z) and is extruded along x.
  const s = new THREE.Shape();
  s.moveTo(-Dp / 2, 0);
  s.lineTo(Dp / 2, 0);
  s.lineTo(Dp / 2, H);
  s.lineTo(-Dp / 2 + 0.07, H);
  s.lineTo(-Dp / 2, 0.035);
  s.closePath();
  const prof = new THREE.ExtrudeGeometry(s, {
    depth: W,
    bevelEnabled: true,
    bevelSize: 0.004,
    bevelThickness: 0.004,
    bevelSegments: 2,
  });
  const pos = prof.attributes.position;
  for (let i = 0; i < pos.count; i++)
    pos.setXYZ(i, pos.getZ(i) - W / 2, pos.getX(i), pos.getY(i));
  prof.computeVertexNormals();
  const housing = new THREE.Mesh(prof, shell);
  housing.position.set(cx, cy, 0);
  g.add(housing);
  for (const fx of [-W / 2 + 0.02, W / 2 - 0.02])
    for (const fy of [-Dp / 2 + 0.03, Dp / 2 - 0.03])
      add(
        new THREE.CylinderGeometry(0.009, 0.011, 0.008, 16).rotateX(
          Math.PI / 2,
        ),
        dark,
        cx + fx,
        cy + fy,
        -0.002,
      );
  const [px, py, pz] = BALANCE.pan,
    P = BALANCE.panSize;
  add(
    new THREE.CylinderGeometry(0.03, 0.035, 0.008, 24).rotateX(Math.PI / 2),
    dark,
    px,
    py,
    H + 0.004,
  );
  add(new THREE.BoxGeometry(P, P, 0.003), steel, px, py, pz - 0.0015);
  add(
    new THREE.BoxGeometry(P + 0.004, 0.004, 0.006),
    steel,
    px,
    py - P / 2,
    pz - 0.001,
  );
  add(
    new THREE.BoxGeometry(P + 0.004, 0.004, 0.006),
    steel,
    px,
    py + P / 2,
    pz - 0.001,
  );
  add(
    new THREE.CylinderGeometry(0.008, 0.008, 0.003, 20).rotateX(Math.PI / 2),
    new THREE.MeshStandardMaterial({ color: 0x9ccbe0, roughness: 0.2 }),
    cx + W / 2 - 0.025,
    cy + Dp / 2 - 0.025,
    H + 0.0015,
  );
  const canvas = document.createElement("canvas");
  canvas.width = 512;
  canvas.height = 128;
  const ctx = canvas.getContext("2d")!;
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  const slope = Math.atan2(H - 0.035, 0.07);
  const disp = add(
    new THREE.PlaneGeometry(W * 0.72, 0.05),
    new THREE.MeshBasicMaterial({ map: tex }),
    cx,
    cy - Dp / 2 + 0.035,
    (0.035 + H) / 2 + 0.002,
  );
  disp.rotation.set(slope, 0, 0);
  disp.position.y -= Math.sin(slope) * 0.007;
  disp.position.z += Math.cos(slope) * 0.007;
  for (let i = 0; i < 4; i++)
    add(
      new THREE.BoxGeometry(0.018, 0.008, 0.004),
      dark,
      cx - 0.045 + i * 0.03,
      cy - Dp / 2 + 0.012,
      0.03,
    ).rotation.x = slope;
  let last = "";
  function setReading(text: string, stable: boolean) {
    const key = text + stable;
    if (key === last) return;
    last = key;
    ctx.fillStyle = "#121917";
    ctx.fillRect(0, 0, 512, 128);
    ctx.fillStyle = stable ? "#8ff0b0" : "#e2c46a";
    ctx.font = "600 78px ui-monospace, monospace";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    ctx.fillText(text, 430, 68);
    ctx.font = "500 40px ui-monospace, monospace";
    ctx.textAlign = "left";
    ctx.fillText("g", 446, 72);
    ctx.font = "500 26px ui-monospace, monospace";
    ctx.fillStyle = stable ? "#8ff0b0" : "#5b6b62";
    ctx.fillText(stable ? "*" : "~", 20, 36);
    tex.needsUpdate = true;
  }
  setReading("0.000", true);
  return { group: g, setReading };
}
