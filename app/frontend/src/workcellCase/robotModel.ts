// UR5e (Universal Robots meshes) + Robotiq 2F-140, posed from joint angles with the URDF chain.
// The URDF base_link_inertia frame equals the controller base frame of the DH kinematics.
import * as THREE from "three";
import type { GLTF } from "three/examples/jsm/loaders/GLTFLoader.js";

const euler = (r: number, p: number, y: number) =>
  new THREE.Matrix4().makeRotationFromEuler(new THREE.Euler(r, p, y, "ZYX"));
const T = (xyz: number[], rpy: number[]) =>
  euler(rpy[0], rpy[1], rpy[2]).setPosition(xyz[0], xyz[1], xyz[2]);
const rotZ = (q: number) => new THREE.Matrix4().makeRotationZ(q);
const axisRot = (ax: number[], q: number) =>
  new THREE.Matrix4().makeRotationAxis(
    new THREE.Vector3(ax[0], ax[1], ax[2]).normalize(),
    q,
  );

// ur_description/config/ur5e/default_kinematics.yaml
const JOINTS = [
  T([0, 0, 0.1625], [0, 0, 0]),
  T([0, 0, 0], [1.570796327, 0, 0]),
  T([-0.425, 0, 0], [0, 0, 0]),
  T([-0.3922, 0, 0.1333], [0, 0, 0]),
  T([0, -0.0997, 0], [1.570796327, 0, 0]),
  T([0, 0.0996, 0], [1.570796326589793, Math.PI, Math.PI]),
];
const LINKS = ["shoulder", "upperarm", "forearm", "wrist1", "wrist2", "wrist3"];
const TOOL0 = T([0, 0, 0], [0, -Math.PI / 2, -Math.PI / 2]).multiply(
  T([0, 0, 0], [Math.PI / 2, 0, Math.PI / 2]),
);
// Pad gap (m) against finger_joint angle, from the 2F-140 URDF chain.
const GAP: [number, number][] = [
  [0, 0.1285],
  [0.1, 0.1127],
  [0.2, 0.0956],
  [0.3, 0.0777],
  [0.4, 0.0589],
  [0.5, 0.0395],
  [0.6, 0.0198],
  [0.7, 0],
];
export function thetaForGap(gap: number) {
  for (let i = 0; i < GAP.length - 1; i++) {
    const [a, ga] = GAP[i],
      [b, gb] = GAP[i + 1];
    if (gap <= ga && gap >= gb) return a + ((b - a) * (ga - gap)) / (ga - gb);
  }
  return gap > GAP[0][1] ? 0 : 0.7;
}

export function buildRobot(gltf: GLTF) {
  const root = new THREE.Group();
  const groups: Record<string, THREE.Group> = {};
  for (const n of [
    "base",
    ...LINKS,
    "coupling",
    "rqbase",
    "lok",
    "lof",
    "lif",
    "lik",
    "rok",
    "rof",
    "rif",
    "rik",
  ]) {
    const g = new THREE.Group();
    g.matrixAutoUpdate = false;
    root.add(g);
    groups[n] = g;
  }
  const meshes: THREE.Mesh[] = [];
  gltf.scene.traverse((o) => {
    if ((o as THREE.Mesh).isMesh) meshes.push(o as THREE.Mesh);
  });
  const put = (key: string, mesh: THREE.Mesh) => {
    const c = mesh.clone();
    c.position.set(0, 0, 0);
    c.quaternion.identity();
    c.scale.set(1, 1, 1);
    groups[key].add(c);
  };
  for (const o of meshes) {
    const n = o.name,
      m = /^ur_([a-z0-9]+)_/.exec(n);
    if (m) put(m[1], o);
    else if (n.startsWith("rq_base_link")) put("rqbase", o);
    else if (n.startsWith("rq_coupling")) put("coupling", o);
    else if (n.startsWith("rq_outer_knuckle")) (put("lok", o), put("rok", o));
    else if (n.startsWith("rq_outer_finger")) (put("lof", o), put("rof", o));
    else if (n.startsWith("rq_inner_finger")) (put("lif", o), put("rif", o));
    else if (n.startsWith("rq_inner_knuckle")) (put("lik", o), put("rik", o));
  }
  const padMat = new THREE.MeshStandardMaterial({
    color: 0x2b2d31,
    roughness: 0.85,
  });
  for (const k of ["lif", "rif"]) {
    const pad = new THREE.Mesh(
      new THREE.BoxGeometry(0.027, 0.065, 0.0075),
      padMat,
    );
    pad.position.set(0, 0.0457554015893473, -0.0272203446692936);
    groups[k].add(pad);
  }
  const set = (key: string, m: THREE.Matrix4) => {
    groups[key].matrix.copy(m);
    groups[key].matrixWorldNeedsUpdate = true;
  };
  /** Pose from joint angles (radians) and finger_joint angle; returns the tool0 transform. */
  function pose(q: number[], theta: number) {
    let M = new THREE.Matrix4();
    set("base", M);
    for (let i = 0; i < 6; i++) {
      M = M.clone().multiply(JOINTS[i]).multiply(rotZ(q[i]));
      set(LINKS[i], M);
    }
    const tool0 = M.clone().multiply(TOOL0);
    set(
      "coupling",
      tool0.clone().multiply(new THREE.Matrix4().makeTranslation(0, 0, 0.007)),
    );
    const b = tool0
      .clone()
      .multiply(new THREE.Matrix4().makeTranslation(0, 0, 0.0139))
      .multiply(rotZ(Math.PI / 2));
    set("rqbase", b);
    const k = 2.2957963267948966;
    const lok = b
      .clone()
      .multiply(T([0, -0.030601, 0.054905], [k, 0, 0]))
      .multiply(axisRot([-1, 0, 0], theta));
    const lof = lok
      .clone()
      .multiply(T([0, 0.01821998610742, 0.0260018192872234], [0, 0, 0]));
    const lif = lof
      .clone()
      .multiply(T([0, 0.0817554015893473, -0.0282203446692936], [-0.725, 0, 0]))
      .multiply(axisRot([1, 0, 0], theta));
    const lik = b
      .clone()
      .multiply(T([0, -0.0127, 0.06142], [k, 0, 0]))
      .multiply(axisRot([1, 0, 0], -theta));
    const rok = b
      .clone()
      .multiply(T([0, 0.030601, 0.054905], [k, 0, Math.PI]))
      .multiply(axisRot([1, 0, 0], -theta));
    const rof = rok
      .clone()
      .multiply(T([0, 0.01821998610742, 0.0260018192872234], [0, 0, 0]));
    const rif = rof
      .clone()
      .multiply(T([0, 0.0817554015893473, -0.0282203446692936], [-0.725, 0, 0]))
      .multiply(axisRot([1, 0, 0], theta));
    const rik = b
      .clone()
      .multiply(T([0, 0.0127, 0.06142], [k, 0, -Math.PI]))
      .multiply(axisRot([1, 0, 0], -theta));
    set("lok", lok);
    set("lof", lof);
    set("lif", lif);
    set("lik", lik);
    set("rok", rok);
    set("rof", rof);
    set("rif", rif);
    set("rik", rik);
    return tool0;
  }
  return { group: root, pose };
}
