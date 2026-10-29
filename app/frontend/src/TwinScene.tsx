import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { Twin } from "./instrumentTypes";
import s from "./InstrumentStudio.module.css";

const GAP = 0.25;

/** Lays confirmed and draft twins side by side; only validated box primitives are drawn. */
export default function TwinScene({
  twins,
  active,
  sample,
}: {
  twins: Twin[];
  active?: string | null;
  sample?: string | null;
}) {
  const host = useRef<HTMLDivElement>(null);
  const key =
    JSON.stringify(twins.map((t) => [t.id, t.spec])) + active + sample;
  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
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

    const shown = twins.filter((t) => t.spec);
    const widths = shown.map((t) =>
      Math.max(
        ...t.spec!.parts.map((p) => Math.abs(p.position[0]) * 2 + p.size[0]),
      ),
    );
    const total =
      widths.reduce((a, w) => a + w, 0) + GAP * Math.max(0, shown.length - 1);
    let x = -total / 2;
    let height = 0.4;
    const disposables: { dispose: () => void }[] = [];
    shown.forEach((twin, i) => {
      const group = new THREE.Group();
      group.position.x = x + widths[i] / 2;
      x += widths[i] + GAP;
      for (const part of twin.spec!.parts) {
        const geometry = new THREE.BoxGeometry(...part.size);
        const material = new THREE.MeshStandardMaterial({
          color: part.color,
          roughness: 0.7,
          emissive:
            twin.id === active
              ? new THREE.Color("#b94825")
              : new THREE.Color(0),
          emissiveIntensity: twin.id === active ? 0.35 : 0,
          transparent: !twin.confirmed,
          opacity: twin.confirmed ? 1 : 0.55,
        });
        const mesh = new THREE.Mesh(geometry, material);
        mesh.position.set(...part.position);
        group.add(mesh);
        disposables.push(geometry, material);
        height = Math.max(height, part.position[1] + part.size[1] / 2);
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
    const floor = new THREE.GridHelper(
      Math.max(2, total + 1),
      20,
      0x6f8a78,
      0x3a4c42,
    );
    scene.add(floor);
    disposables.push(floor.geometry, floor.material as THREE.Material);
    const distance = Math.max(1.4, total * 1.1, height * 2.4);
    camera.position.set(distance * 0.55, distance * 0.5, distance);
    controls.target.set(0, height / 2, 0);

    const resize = () => {
      const { width, height: h } = el.getBoundingClientRect();
      renderer.setSize(width, h, false);
      camera.aspect = width / Math.max(1, h);
      camera.updateProjectionMatrix();
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
      disposables.forEach((d) => d.dispose());
      renderer.dispose();
      renderer.domElement.remove();
    };
    // `key` captures every input that changes the scene.
  }, [key]);
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
              .join(", ")}`
          : "Empty workcell"
      }
    />
  );
}
