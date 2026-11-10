// Registered 3D models drawn in place of a twin's planning box. Every file is checked
// against its pinned sha256; a missing or changed file leaves the box in place.
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { api } from "./api";
import type { Mesh, TwinSpec } from "./instrumentTypes";
import { footprint } from "./layoutGeometry";
import type { Deck } from "./workcellCase/cell";
import { buildBalance } from "./workcellCase/balanceModel";
import { buildOT2 } from "./workcellCase/ot2Model";
import { buildRobot } from "./workcellCase/robotModel";

type Registry = {
  base_path: string;
  assets: { id: string; file: string | null; sha256: string | null }[];
};

const hex = (b: ArrayBuffer) =>
  [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, "0")).join("");

const files = new Map<string, Promise<ArrayBuffer>>();
function verified(url: string, sha256: string) {
  if (!files.has(url))
    files.set(
      url,
      (async () => {
        const response = await fetch(url);
        if (!response.ok) throw new Error(`${url}: ${response.status}`);
        const bytes = await response.arrayBuffer();
        if (hex(await crypto.subtle.digest("SHA-256", bytes)) !== sha256)
          throw new Error(`${url} does not match its pinned digest`);
        return bytes;
      })(),
    );
  return files.get(url)!;
}

let registry: Promise<Registry> | null = null;
async function registered(id: string) {
  registry ??= api<Registry>("/workcell/assets");
  const reg = await registry;
  const asset = reg.assets.find((a) => a.id === id);
  if (!asset?.file || !asset.sha256)
    throw new Error(`${id} is not a file asset`);
  return verified(reg.base_path + asset.file, asset.sha256);
}

const templates = new Map<string, Promise<THREE.Object3D>>();
/** A shared Z-up template for an instrument model; clone it before adding it to a scene. */
export function instrumentModel(mesh: Mesh): Promise<THREE.Object3D> {
  const key = mesh.kind === "glb" ? mesh.url! : mesh.kind;
  if (!templates.has(key))
    templates.set(
      key,
      (async () => {
        if (mesh.kind === "glb") {
          const bytes = await verified(mesh.url!, mesh.sha256!);
          return (await new GLTFLoader().parseAsync(bytes, "")).scene;
        }
        if (mesh.kind === "ot2") {
          const decks = JSON.parse(
            new TextDecoder().decode(await registered("opentrons-decks")),
          ) as { ot2: Deck };
          return buildOT2(decks.ot2).group;
        }
        if (mesh.kind === "balance") return buildBalance().group;
        throw new Error(`No instrument model for ${mesh.kind}`);
      })(),
    );
  return templates.get(key)!;
}

let robotFile: Promise<ArrayBuffer> | null = null;
/** A posable UR5e with Robotiq 2F-140, in the controller base frame (Z up). */
export async function armModel() {
  robotFile ??= registered("ur5e-robotiq-2f140");
  const gltf = await new GLTFLoader().parseAsync(await robotFile, "");
  return buildRobot(gltf);
}

/**
 * The model turned Y up and moved so its envelope stands on the twin's footprint
 * centre, front toward the twin's +Z like the planning box.
 */
export function fitted(template: THREE.Object3D, spec: TwinSpec) {
  const holder = new THREE.Group();
  const upright = new THREE.Group();
  upright.rotation.x = -Math.PI / 2; // Z-up model: its front, -Y, becomes +Z
  upright.add(template.clone(true));
  holder.add(upright);
  holder.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(upright);
  const { x0, x1, z0, z1 } = footprint(spec);
  const centre = box.getCenter(new THREE.Vector3());
  upright.position.set(
    (x0 + x1) / 2 - centre.x,
    -box.min.y,
    (z0 + z1) / 2 - centre.z,
  );
  return holder;
}
