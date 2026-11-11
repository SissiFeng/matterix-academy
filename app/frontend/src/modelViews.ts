// Library model thumbnails and previews. Thumbnails are drawn one at a time on a single
// shared WebGL context, so a page of cards never opens one context per card.
import * as THREE from "three";
import { looseModel } from "./instrumentModels";
import type { Mesh } from "./instrumentTypes";

const THUMB = 360;
const VIEW = new THREE.Vector3(0.75, 0.55, 1).normalize();

export function lit(scene: THREE.Scene) {
  scene.add(new THREE.HemisphereLight(0xffffff, 0x445544, 2.2));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6);
  sun.position.set(2, 4, 3);
  const fill = new THREE.DirectionalLight(0xffffff, 0.5);
  fill.position.set(-2, 1.5, -1);
  scene.add(sun, fill);
}

/** The Z-up model turned Y up, standing on the floor at the origin. */
export function upright(object: THREE.Object3D) {
  const holder = new THREE.Group();
  const turned = new THREE.Group();
  turned.rotation.x = -Math.PI / 2;
  turned.add(object);
  holder.add(turned);
  holder.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(turned);
  const centre = box.getCenter(new THREE.Vector3());
  turned.position.set(-centre.x, -box.min.y, -centre.z);
  holder.updateMatrixWorld(true);
  return holder;
}

/** Points the camera at the whole object from the front-right, filling the frame. */
export function aim(
  camera: THREE.PerspectiveCamera,
  object: THREE.Object3D,
  aspect: number,
) {
  const box = new THREE.Box3().setFromObject(object);
  const centre = box.getCenter(new THREE.Vector3());
  const radius = Math.max(0.05, box.getSize(new THREE.Vector3()).length() / 2);
  camera.aspect = aspect;
  const half = Math.atan(
    Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2) * Math.min(1, aspect),
  );
  const distance = (radius / Math.sin(half)) * 1.02;
  camera.position.copy(centre).addScaledVector(VIEW, distance);
  camera.near = distance / 100;
  camera.far = distance * 10;
  camera.lookAt(centre);
  camera.updateProjectionMatrix();
  return centre;
}

let renderer: THREE.WebGLRenderer | null | undefined;
let queue: Promise<unknown> = Promise.resolve();
const thumbs = new Map<string, Promise<string | null>>();

/** A still of the model as an image URL, or null when it cannot be drawn. */
export function thumbnail(mesh: Mesh): Promise<string | null> {
  const key = mesh.url ?? mesh.kind;
  if (!thumbs.has(key)) {
    const drawn = queue.then(() => draw(mesh));
    queue = drawn.catch(() => undefined);
    thumbs.set(key, drawn);
  }
  return thumbs.get(key)!;
}

async function draw(mesh: Mesh) {
  if (renderer === undefined)
    try {
      renderer = new THREE.WebGLRenderer({
        antialias: true,
        alpha: true,
        preserveDrawingBuffer: true,
      });
      renderer.setPixelRatio(1);
      renderer.setSize(THUMB, THUMB, false);
      renderer.outputColorSpace = THREE.SRGBColorSpace;
    } catch {
      renderer = null;
    }
  if (!renderer) return null;
  let model;
  try {
    model = await looseModel(mesh);
  } catch (e) {
    console.warn((e as Error).message);
    return null;
  }
  const scene = new THREE.Scene();
  lit(scene);
  scene.add(upright(model.object));
  const camera = new THREE.PerspectiveCamera(30, 1, 0.01, 50);
  aim(camera, scene, 1);
  renderer.render(scene, camera);
  const url = renderer.domElement.toDataURL("image/webp", 0.86);
  model.release();
  return url;
}
