import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { ArmFrame, Layout, Twin, Vec } from "./instrumentTypes";
import { ARM_RADII } from "./layoutGeometry";
import s from "./InstrumentStudio.module.css";

const GAP = 0.25;
const UP = new THREE.Vector3(0, 1, 0);

/**
 * Draws confirmed and draft twins; only validated box primitives are drawn. Without a
 * layout the twins sit side by side; with one they sit where they are placed and the
 * planned arm (capsules from server-computed joint points) is drawn on top.
 */
export default function TwinScene({
  twins,
  active,
  sample,
  layout,
  arm,
  path,
  blocked,
}: {
  twins: Pick<Twin, "id" | "spec" | "confirmed">[];
  active?: string | null;
  sample?: string | null;
  layout?: Layout | null;
  arm?: ArmFrame | null;
  path?: Vec[] | null;
  blocked?: string | null;
}) {
  const host = useRef<HTMLDivElement>(null);
  const overlay = useRef<THREE.Group | null>(null);
  const key =
    JSON.stringify([twins.map((t) => [t.id, t.spec]), layout]) +
    active +
    sample +
    blocked;
  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      const fallback = document.createElement("p");
      fallback.textContent =
        "3D preview is unavailable in this browser. Instrument editing and synthetic workflow execution remain available.";
      fallback.setAttribute("role", "status");
      el.appendChild(fallback);
      return () => fallback.remove();
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    scene.add(new THREE.HemisphereLight(0xffffff, 0x445544, 2.2));
    const sun = new THREE.DirectionalLight(0xffffff, 1.6);
    sun.position.set(2, 4, 3);
    scene.add(sun);
    const camera = new THREE.PerspectiveCamera(38, 1, 0.01, 50);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    const disposables: { dispose: () => void }[] = [];

    const placed = new Map(layout?.placements.map((p) => [p.twin_id, p]));
    const shown = twins.filter((t) => t.spec && (!layout || placed.has(t.id)));
    const widths = shown.map((t) =>
      Math.max(
        ...t.spec!.parts.map((p) => Math.abs(p.position[0]) * 2 + p.size[0]),
      ),
    );
    const total =
      widths.reduce((a, w) => a + w, 0) + GAP * Math.max(0, shown.length - 1);
    let x = -total / 2;
    shown.forEach((twin, i) => {
      const group = new THREE.Group();
      const placement = placed.get(twin.id);
      if (placement) {
        group.position.set(placement.x, 0, placement.z);
        group.rotation.y = (placement.yaw * Math.PI) / 180;
      } else group.position.x = x + widths[i] / 2;
      x += widths[i] + GAP;
      const glow =
        twin.id === blocked ? "#d0402a" : twin.id === active ? "#b94825" : null;
      for (const part of twin.spec!.parts) {
        const geometry = new THREE.BoxGeometry(...part.size);
        const material = new THREE.MeshStandardMaterial({
          color: part.color,
          roughness: 0.7,
          emissive: glow ? new THREE.Color(glow) : new THREE.Color(0),
          emissiveIntensity: glow ? (twin.id === blocked ? 0.6 : 0.35) : 0,
          transparent: !twin.confirmed,
          opacity: twin.confirmed ? 1 : 0.55,
        });
        const mesh = new THREE.Mesh(geometry, material);
        mesh.position.set(...part.position);
        group.add(mesh);
        disposables.push(geometry, material);
      }
      if (twin.id === sample) {
        const top = Math.max(
          ...twin.spec!.parts.map((p) => p.position[1] + p.size[1] / 2),
        );
        const geometry = new THREE.SphereGeometry(0.035, 20, 14);
        const material = new THREE.MeshStandardMaterial({
          color: "#d9a43b",
          emissive: "#d9a43b",
          emissiveIntensity: 0.5,
        });
        const marker = new THREE.Mesh(geometry, material);
        marker.position.set(0, top + 0.06, 0);
        group.add(marker);
        disposables.push(geometry, material);
      }
      scene.add(group);
    });
    if (layout) {
      const geometry = new THREE.BoxGeometry(
        layout.bench.width,
        0.02,
        layout.bench.depth,
      );
      const material = new THREE.MeshStandardMaterial({
        color: "#41574b",
        roughness: 0.9,
      });
      const bench = new THREE.Mesh(geometry, material);
      bench.position.y = -0.011;
      scene.add(bench);
      disposables.push(geometry, material);
    }
    const bounds = new THREE.Box3().setFromObject(scene);
    if (bounds.isEmpty())
      bounds.set(
        new THREE.Vector3(-0.5, 0, -0.5),
        new THREE.Vector3(0.5, 0.5, 0.5),
      );
    // Leave headroom for the arm above its pedestal.
    if (layout) bounds.max.y = Math.max(bounds.max.y, 1.3);
    const center = bounds.getCenter(new THREE.Vector3());
    const radius = Math.max(
      0.5,
      bounds.getSize(new THREE.Vector3()).length() / 2,
    );
    const direction = new THREE.Vector3(0.55, 0.5, 1).normalize();
    const span = layout
      ? Math.max(layout.bench.width, layout.bench.depth)
      : total;
    const floor = new THREE.GridHelper(
      Math.max(2, span + 1),
      20,
      0x6f8a78,
      0x3a4c42,
    );
    floor.position.y = layout ? -0.022 : 0;
    scene.add(floor);
    disposables.push(floor.geometry, floor.material as THREE.Material);
    const group = new THREE.Group();
    scene.add(group);
    overlay.current = group;
    controls.target.copy(center);

    const resize = () => {
      const { width, height: h } = el.getBoundingClientRect();
      renderer.setSize(width, h, false);
      camera.aspect = Math.max(1, width) / Math.max(1, h);
      const halfAngle = Math.atan(
        Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2) *
          Math.min(1, camera.aspect),
      );
      const distance = (radius / Math.sin(halfAngle)) * 1.1;
      camera.position.copy(center).addScaledVector(direction, distance);
      camera.far = Math.max(50, distance * 10);
      camera.updateProjectionMatrix();
      controls.update();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(el);
    resize();
    let frame = 0;
    const tick = () => {
      controls.update();
      renderer.render(scene, camera);
      frame = requestAnimationFrame(tick);
    };
    tick();
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      controls.dispose();
      clear(group);
      overlay.current = null;
      disposables.forEach((d) => d.dispose());
      renderer.dispose();
      renderer.domElement.remove();
    };
    // `key` captures every input that changes the scene.
  }, [key]);

  // The arm changes every animation frame, so it lives in its own group.
  const armKey = JSON.stringify([arm, path]);
  useEffect(() => {
    const group = overlay.current;
    if (!group) return;
    clear(group);
    const metal = new THREE.MeshStandardMaterial({
      color: blocked ? "#e6a08a" : "#d8dde3",
      roughness: 0.35,
      metalness: 0.4,
    });
    if (arm) {
      arm.slice(0, -1).forEach((a, i) => {
        const from = new THREE.Vector3(...a);
        const to = new THREE.Vector3(...arm[i + 1]);
        const length = from.distanceTo(to);
        const r = ARM_RADII[i];
        const joint = new THREE.Mesh(
          new THREE.SphereGeometry(r, 18, 12),
          metal,
        );
        joint.position.copy(from);
        group.add(joint);
        if (length < 1e-4) return;
        const link = new THREE.Mesh(
          new THREE.CylinderGeometry(r, r, length, 18),
          metal,
        );
        link.position.copy(from).lerp(to, 0.5);
        link.quaternion.setFromUnitVectors(
          UP,
          to.clone().sub(from).normalize(),
        );
        group.add(link);
      });
    }
    if (path && path.length > 1) {
      const line = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(
          path.map((p) => new THREE.Vector3(...p)),
        ),
        new THREE.LineBasicMaterial({ color: blocked ? "#ff7a59" : "#f2c14e" }),
      );
      group.add(line);
    }
    return () => {
      clear(group);
      metal.dispose();
    };
  }, [armKey, key, blocked]);

  return (
    <div
      ref={host}
      className={s.scene}
      role="img"
      aria-label={
        twins.length
          ? `3D preview of ${twins
              .filter((t) => t.spec)
              .map((t) => t.spec!.name)
              .join(", ")}${arm ? " with the planned arm pose" : ""}`
          : "Empty workcell"
      }
    />
  );
}

function clear(group: THREE.Group) {
  for (const child of [...group.children]) {
    group.remove(child);
    const object = child as THREE.Mesh;
    object.geometry?.dispose();
    const material = object.material as THREE.Material | undefined;
    // Shared arm material is disposed by its effect.
    if (material && child.type === "Line") material.dispose();
  }
}
