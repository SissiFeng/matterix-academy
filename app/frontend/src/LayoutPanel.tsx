import { useRef, useState } from "react";
import { Download, RotateCw, Trash2 } from "lucide-react";
import type {
  Access,
  Layout,
  LayoutPreview,
  Placement,
  Twin,
  TwinSpec,
} from "./instrumentTypes";
import {
  REACH,
  centre,
  conflicts,
  corners,
  frontFace,
  isArm,
  type Point,
} from "./layoutGeometry";
import studio from "./InstrumentStudio.module.css";
import s from "./LayoutPanel.module.css";

const PAD = 0.12;
const round = (v: number) => Math.round(v * 100) / 100;
const clamp = (v: number, limit: number) =>
  Math.max(-limit, Math.min(limit, v));
const wrapYaw = (v: number) => ((((v + 180) % 360) + 360) % 360) - 180;

export default function LayoutPanel({
  twins,
  layout,
  onChange,
  preview,
  checking,
  selectedMotion,
  onSelectMotion,
  onSave,
  saveDisabled,
  onExport,
}: {
  twins: Twin[];
  layout: Layout;
  onChange: (next: Layout) => void;
  preview: LayoutPreview | null;
  checking: boolean;
  selectedMotion: number;
  onSelectMotion: (index: number) => void;
  onSave: () => void;
  saveDisabled: boolean;
  /** Present only while the previewed layout is the saved one. */
  onExport?: (step: number, speed: number) => void;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [speed, setSpeed] = useState(20);
  const svg = useRef<SVGSVGElement>(null);
  const drag = useRef<{ id: string; dx: number; dz: number } | null>(null);
  const specs = new Map(
    twins.map((t) => [t.id, t.spec!] as [string, TwinSpec]),
  );
  const name = (id: string | null) => (id && specs.get(id)?.name) || "—";
  const bad = conflicts(layout, specs);
  const placed = new Set(layout.placements.map((p) => p.twin_id));
  const current = layout.placements.find((p) => p.twin_id === selected);
  const { width, depth } = layout.bench;

  const update = (id: string, patch: Partial<Placement>) =>
    onChange({
      ...layout,
      placements: layout.placements.map((p) =>
        p.twin_id === id
          ? {
              ...p,
              ...patch,
              x: round(clamp(patch.x ?? p.x, 2)),
              z: round(clamp(patch.z ?? p.z, 1.5)),
              yaw: wrapYaw(patch.yaw ?? p.yaw),
            }
          : p,
      ),
    });
  const toBench = (event: React.PointerEvent): Point => {
    const matrix = svg.current!.getScreenCTM()!.inverse();
    const pt = new DOMPoint(event.clientX, event.clientY).matrixTransform(
      matrix,
    );
    return [pt.x, pt.y];
  };

  const motions = preview?.motions ?? [];
  const entries = [
    ...motions.map((m) => ({ ...m, blocked: null as string | null })),
    ...(preview?.blocked
      ? [
          {
            ...preview.blocked,
            blocked: preview.blocked.blocked_by,
            length_m: 0,
            clearance_m: 0,
            planner: null,
          },
        ]
      : []),
  ];

  return (
    <>
      <h2>Lay out the bench</h2>
      <p className={studio.muted}>
        Drag instruments to where they stand, or select one and use the arrow
        keys (Shift for 10 cm, R to rotate). Each transfer robot is a{" "}
        {preview?.arm ?? "UR5e"} on its own pedestal; every transfer in the
        saved workflow is checked for link collisions.
      </p>
      <svg
        ref={svg}
        className={s.bench}
        viewBox={`${-width / 2 - PAD} ${-depth / 2 - PAD} ${width + 2 * PAD} ${depth + 2 * PAD}`}
        role="group"
        aria-label={`Bench top view, ${width} by ${depth} metres`}
        onPointerMove={(e) => {
          if (!drag.current) return;
          const [x, z] = toBench(e);
          update(drag.current.id, {
            x: x - drag.current.dx,
            z: z - drag.current.dz,
          });
        }}
        onPointerUp={() => (drag.current = null)}
        onPointerCancel={() => (drag.current = null)}
      >
        <rect
          className={s.surface}
          x={-width / 2}
          y={-depth / 2}
          width={width}
          height={depth}
        />
        {Array.from({ length: Math.floor(width * 10) + 1 }, (_, i) => (
          <line
            key={`x${i}`}
            className={s.grid}
            x1={-width / 2 + i / 10}
            x2={-width / 2 + i / 10}
            y1={-depth / 2}
            y2={depth / 2}
          />
        ))}
        {Array.from({ length: Math.floor(depth * 10) + 1 }, (_, i) => (
          <line
            key={`z${i}`}
            className={s.grid}
            y1={-depth / 2 + i / 10}
            y2={-depth / 2 + i / 10}
            x1={-width / 2}
            x2={width / 2}
          />
        ))}
        {layout.placements.map((p) => {
          const spec = specs.get(p.twin_id);
          if (!spec || !isArm({ spec })) return null;
          const [cx, cz] = centre(spec, p);
          return (
            <circle
              key={`reach-${p.twin_id}`}
              className={s.reach}
              cx={cx}
              cy={cz}
              r={preview?.reach_m ?? REACH}
            />
          );
        })}
        {layout.placements.map((p) => {
          const spec = specs.get(p.twin_id);
          if (!spec) return null;
          const shape = corners(spec, p);
          const [cx, cz] = centre(spec, p);
          const [fx, fz] = frontFace(spec, p);
          const arm = isArm({ spec });
          const classes = [
            s.footprint,
            arm ? s.arm : "",
            p.twin_id === selected ? s.selected : "",
            bad.has(p.twin_id) || preview?.blocked?.blocked_by === spec.name
              ? s.conflict
              : "",
          ].join(" ");
          return (
            <g
              key={p.twin_id}
              className={classes}
              tabIndex={0}
              role="button"
              aria-pressed={p.twin_id === selected}
              aria-label={`${spec.name} at x ${p.x} m, z ${p.z} m, ${p.yaw}°`}
              onPointerDown={(e) => {
                setSelected(p.twin_id);
                const [x, z] = toBench(e);
                drag.current = { id: p.twin_id, dx: x - p.x, dz: z - p.z };
                svg.current!.setPointerCapture(e.pointerId);
              }}
              onFocus={() => setSelected(p.twin_id)}
              onKeyDown={(e) => {
                const step = e.shiftKey ? 0.1 : 0.01;
                const moves: Record<string, Partial<Placement>> = {
                  ArrowLeft: { x: p.x - step },
                  ArrowRight: { x: p.x + step },
                  ArrowUp: { z: p.z - step },
                  ArrowDown: { z: p.z + step },
                  r: { yaw: p.yaw + 15 },
                  R: { yaw: p.yaw - 15 },
                };
                if (!(e.key in moves)) return;
                e.preventDefault();
                update(p.twin_id, moves[e.key]);
              }}
            >
              <polygon
                points={shape.map((c) => c.join(",")).join(" ")}
                style={{ fill: spec.parts[0].color }}
              />
              {!arm &&
                (p.access === "front" ? (
                  <circle className={s.access} cx={fx} cy={fz} r={0.025} />
                ) : (
                  <circle className={s.access} cx={cx} cy={cz} r={0.025} />
                ))}
              <text x={cx} y={cz - 0.05} className={s.label}>
                {spec.name}
              </text>
            </g>
          );
        })}
      </svg>
      <div className={s.benchSize}>
        {(["width", "depth"] as const).map((dim) => (
          <label key={dim}>
            Bench {dim} (m)
            <input
              type="number"
              step={0.1}
              min={dim === "width" ? 0.6 : 0.4}
              max={dim === "width" ? 4 : 3}
              value={layout.bench[dim]}
              onChange={(e) =>
                onChange({
                  ...layout,
                  bench: { ...layout.bench, [dim]: Number(e.target.value) },
                })
              }
            />
          </label>
        ))}
      </div>

      {current ? (
        <fieldset className={s.selectedFields}>
          <legend>{name(current.twin_id)}</legend>
          {(["x", "z"] as const).map((axis) => (
            <label key={axis}>
              {axis.toUpperCase()} (m)
              <input
                type="number"
                step={0.01}
                aria-label={`${name(current.twin_id)} ${axis}`}
                value={current[axis]}
                onChange={(e) =>
                  update(current.twin_id, { [axis]: Number(e.target.value) })
                }
              />
            </label>
          ))}
          <label>
            Yaw (°)
            <input
              type="number"
              step={15}
              aria-label={`${name(current.twin_id)} yaw`}
              value={current.yaw}
              onChange={(e) =>
                update(current.twin_id, { yaw: Number(e.target.value) })
              }
            />
          </label>
          {!isArm({ spec: specs.get(current.twin_id)! }) && (
            <label>
              Access
              <select
                aria-label={`${name(current.twin_id)} access`}
                value={current.access}
                onChange={(e) =>
                  update(current.twin_id, { access: e.target.value as Access })
                }
              >
                <option value="top">From above</option>
                <option value="front">Front face</option>
              </select>
            </label>
          )}
          <div className={s.fieldTools}>
            <button
              className={studio.secondary}
              onClick={() => update(current.twin_id, { yaw: current.yaw + 90 })}
            >
              <RotateCw size={14} /> Rotate 90°
            </button>
            <button
              className={studio.secondary}
              onClick={() => {
                setSelected(null);
                onChange({
                  ...layout,
                  placements: layout.placements.filter(
                    (p) => p.twin_id !== current.twin_id,
                  ),
                });
              }}
            >
              <Trash2 size={14} /> Take off bench
            </button>
          </div>
        </fieldset>
      ) : (
        <p className={studio.muted}>Select an instrument to edit its pose.</p>
      )}
      {twins.some((t) => !placed.has(t.id)) && (
        <div className={s.unplaced}>
          <strong>Not on the bench</strong>
          {twins
            .filter((t) => !placed.has(t.id))
            .map((t) => (
              <button
                key={t.id}
                className={studio.secondary}
                onClick={() => {
                  setSelected(t.id);
                  onChange({
                    ...layout,
                    placements: [
                      ...layout.placements,
                      {
                        twin_id: t.id,
                        x: 0,
                        z: round(depth / 2 - 0.3),
                        yaw: 0,
                        access: "top",
                      },
                    ],
                  });
                }}
              >
                Place {t.spec!.name}
              </button>
            ))}
        </div>
      )}

      <div className={s.motions} aria-live="polite">
        <strong>
          Arm paths{" "}
          <small>
            {bad.size
              ? "fix highlighted footprints first"
              : checking
                ? "checking…"
                : "synthetic geometry check"}
          </small>
        </strong>
        {bad.size > 0 && (
          <p className={s.problem}>
            {[...bad].map(name).join(", ")}{" "}
            {bad.size === 1
              ? "overlaps another instrument or leaves"
              : "overlap or leave"}{" "}
            the bench.
          </p>
        )}
        {!bad.size && preview?.error && (
          <p className={s.problem} role="status">
            {preview.error.message}
          </p>
        )}
        {!bad.size && !preview?.error && preview && !motions.length && (
          <p className={studio.muted}>
            Save a workflow with a transfer step to plan the arm's path.
          </p>
        )}
        <ol>
          {entries.map((m, i) => (
            <li key={`${m.step}-${i}`} className={s.motionRow}>
              <button
                className={`${s.motion} ${i === selectedMotion ? s.motionActive : ""} ${m.blocked ? s.motionBlocked : ""}`}
                onClick={() => onSelectMotion(i)}
                aria-pressed={i === selectedMotion}
              >
                <span>
                  Step {m.step} · {name(m.source_id)} → {name(m.target_id)}
                </span>
                <small>
                  {m.blocked
                    ? `Blocked by ${m.blocked}${preview?.blocked?.link ? ` (${preview.blocked.link})` : ""}`
                    : `${m.length_m.toFixed(2)} m tool path · ${(m.clearance_m * 100).toFixed(1)} cm min clearance · ${m.planner}`}
                </small>
              </button>
              {onExport && !m.blocked && (
                <button
                  className={studio.secondary}
                  aria-label={`Download step ${m.step} as a UR5e action chain`}
                  title="ur5e.action-chain/2 for the UR5e SiLA connector's Action Composer"
                  onClick={() => onExport(m.step, speed)}
                >
                  <Download size={14} /> UR5e chain
                </button>
              )}
            </li>
          ))}
        </ol>
        {onExport && motions.length > 0 && (
          <div className={s.export}>
            <label>
              Connector speed (°/s)
              <input
                type="number"
                min={1}
                max={40}
                step={1}
                value={speed}
                onChange={(e) => setSpeed(Number(e.target.value))}
              />
            </label>
            <small>
              Import into the UR5e SiLA connector's Action Composer, start at
              the reference pose and validate in simulation. Real-device
              execution stays behind the connector's own qualification gate.
            </small>
          </div>
        )}
        {!onExport && motions.length > 0 && (
          <small className={s.hint}>
            Save the layout to download arm paths for the UR5e SiLA connector.
          </small>
        )}
      </div>
      <div className={studio.actions}>
        <button
          className={studio.primary}
          disabled={saveDisabled || bad.size > 0}
          onClick={onSave}
        >
          Save layout
        </button>
      </div>
      <p className={studio.notice}>
        Capsule links and box instruments only: no self-collision, dynamics,
        cables or calibrated poses. A clear path here is synthetic and is not
        motion-planning, Isaac/GPU or physical robot validation.
      </p>
    </>
  );
}
