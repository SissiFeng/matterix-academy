import { useEffect, useMemo, useRef, useState } from "react";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { ArrowLeft, Pause, Play } from "lucide-react";
import { api, json as body } from "../api";
import { CellEngine, type ChartData, type Snapshot, type View } from "./engine";
import { NAMES, LIMIT_DEG } from "./kin";
import s from "./WorkcellCase.module.css";

type Asset = {
  id: string;
  kind: string;
  name: string;
  media_type: string;
  file: string | null;
  sha256: string | null;
  size_bytes: number | null;
  license: string;
  sources: { repository: string; commit: string | null; paths: string[] }[];
  frame: string;
  notes: string;
};
type CaseDef = {
  id: string;
  name: string;
  summary: string;
  devices: { id: string; name: string; role: string; asset: string }[];
  assets: Asset[];
  base_path: string;
  evidence: "synthetic";
};

const hex = (b: ArrayBuffer) =>
  [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, "0")).join("");
async function loadAssets(def: CaseDef) {
  const bytes: Record<string, ArrayBuffer> = {};
  await Promise.all(
    def.assets
      .filter((a) => a.file)
      .map(async (a) => {
        const r = await fetch(def.base_path + a.file);
        if (!r.ok)
          throw new Error(`${a.name} could not be loaded (${r.status}).`);
        const b = await r.arrayBuffer();
        if (hex(await crypto.subtle.digest("SHA-256", b)) !== a.sha256)
          throw new Error(`${a.name} does not match its registered digest.`);
        bytes[a.id] = b;
      }),
  );
  const text = (id: string) => JSON.parse(new TextDecoder().decode(bytes[id]));
  const glb = (id: string) => new GLTFLoader().parseAsync(bytes[id], "");
  const [flex, robot] = await Promise.all([
    glb("opentrons-flex-shell"),
    glb("ur5e-robotiq-2f140"),
  ]);
  return {
    decks: text("opentrons-decks"),
    labware: text("opentrons-labware"),
    flexMeta: text("opentrons-flex-shell-frames"),
    flex,
    robot,
  };
}

const LANE: Record<string, [string, string]> = {
  flex: ["Flex", "var(--lane-flex)"],
  ot2: ["OT-2", "var(--lane-ot2)"],
  ur: ["UR5e", "var(--lane-ur)"],
  bal: ["Balance", "var(--lane-bal)"],
  cell: ["Cell", "var(--brand-text)"],
  design: ["Design", "var(--accent)"],
};

type ArmSimulation = {
  engine: "mujoco";
  version: string;
  payload_kg: number;
  seconds: number;
  tracking_deg: number;
  torque_ratio: number;
  clearance_m: number;
  self_clearance_m: number;
  nearest: string | null;
  collision: { link: string; blocked_by: string; at_s: number } | null;
  problem: string | null;
};

export default function WorkcellCase({
  caseId,
  onBack,
}: {
  caseId: string;
  onBack: () => void;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const hostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<HTMLCanvasElement>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const engineRef = useRef<CellEngine | null>(null);
  const [def, setDef] = useState<CaseDef | null>(null);
  const [error, setError] = useState("");
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [chart, setChart] = useState<ChartData | null>(null);
  const [tab, setTab] = useState<"flow" | "chain">("flow");
  const [view, setView] = useState<View>("cell");
  const [rate, setRate] = useState(8);
  const [form, setForm] = useState({ name: "Waypoint", hold: 0, grip: "" });
  const [json, setJson] = useState("");
  // A simulated result belongs to the exact chain and speed it was run for.
  const [sim, setSim] = useState<(ArmSimulation & { key: string }) | null>(
    null,
  );
  const [simulating, setSimulating] = useState(false);

  useEffect(() => {
    let alive = true;
    let engine: CellEngine | null = null;
    (async () => {
      try {
        const d = await api<CaseDef>(
          `/workcell/cases/${encodeURIComponent(caseId)}`,
        );
        if (!alive) return;
        setDef(d);
        const assets = await loadAssets(d);
        if (!alive || !hostRef.current || !rootRef.current) return;
        engine = new CellEngine(hostRef.current, rootRef.current, assets);
        engine.onChange = setSnap;
        engine.onChart = setChart;
        engineRef.current = engine;
        (window as unknown as { __workcellCase?: CellEngine }).__workcellCase =
          engine;
        engine.selectJoint(0);
      } catch (e) {
        if (alive) setError((e as Error).message);
      }
    })();
    return () => {
      alive = false;
      engine?.dispose();
      engineRef.current = null;
    };
  }, [caseId]);

  const E = engineRef.current;
  useEffect(() => {
    if (snap?.demo.active)
      setTab(
        snap.t > 0 ||
          snap.demo.title.startsWith("2") ||
          snap.demo.title.startsWith("Run")
          ? "flow"
          : "chain",
      );
  }, [snap?.demo.active, snap?.demo.title, snap?.t]);
  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [snap?.log.length]);
  useEffect(
    () => drawChart(chartRef.current, chart, snap?.joint ?? 0, rootRef.current),
    [chart, snap?.joint],
  );
  const targets = useMemo(() => E?.targets() ?? [], [E]);

  if (error)
    return (
      <div className={s.page} ref={rootRef}>
        <button className={s.back} onClick={onBack}>
          <ArrowLeft size={16} /> Device onboarding
        </button>
        <p className={s.error} role="alert">
          {error}
        </p>
      </div>
    );
  const S = snap;
  const wp = () => ({
    name: form.name.slice(0, 60) || "Waypoint",
    hold: Math.max(0, Math.min(10, form.hold)),
    grip: (form.grip || null) as "close" | "open" | null,
  });
  return (
    <div className={s.page} ref={rootRef}>
      <header className={s.head}>
        <div>
          <button className={s.back} onClick={onBack}>
            <ArrowLeft size={16} /> Device onboarding
          </button>
          <h1>{def?.name ?? "Workcell case"}</h1>
          <p>{def?.summary}</p>
        </div>
        <div className={s.headActions}>
          <span className={s.chipWarn}>Synthetic teaching model</span>
          <button
            className={s.primary}
            disabled={!S}
            onClick={() => (S?.demo.playing ? E?.stopDemo() : E?.startDemo())}
          >
            {S?.demo.playing ? "Stop demo" : "Play demo"}
          </button>
        </div>
      </header>
      <div className={s.grid}>
        <div className={s.main}>
          <div className={s.stage} ref={hostRef} data-testid="workcell-stage">
            {!S && <div className={s.loading}>Loading registered assets…</div>}
            <div className={s.legend} aria-hidden="true">
              <span>
                <i style={{ background: "var(--info)" }} />
                Arm transit
              </span>
              <span>
                <i style={{ background: "var(--ok)" }} />
                Approach
              </span>
              <span>
                <i style={{ background: "var(--accent)" }} />
                Carrying rack
              </span>
              <span>
                <i style={{ background: "var(--danger)" }} />
                Clearance hit
              </span>
              <span>
                <i
                  style={{
                    background:
                      "linear-gradient(90deg,var(--j2),var(--j3),var(--j4),var(--j5),var(--j6))",
                  }}
                />
                J2–J6 trails
              </span>
            </div>
            {S && (
              <div className={s.toggles}>
                <select
                  aria-label="Camera"
                  value={view}
                  onChange={(e) => {
                    setView(e.target.value as View);
                    E?.setView(e.target.value as View);
                  }}
                >
                  <option value="cell">Whole cell</option>
                  <option value="flex">Flex deck</option>
                  <option value="balance">Balance</option>
                  <option value="ot2">OT-2 deck</option>
                </select>
                {(["trails", "path", "keepouts"] as const).map((k) => (
                  <button
                    key={k}
                    aria-pressed={S.toggles[k]}
                    onClick={() => E?.toggle(k)}
                  >
                    {
                      {
                        trails: "Joint trails",
                        path: "Arm path",
                        keepouts: "Keep-outs",
                      }[k]
                    }
                  </button>
                ))}
              </div>
            )}
            {S?.demo.active && (
              <div className={s.caption}>
                <b>{S.demo.title}</b>
                <span>{S.demo.sub}</span>
              </div>
            )}
            {S && <div className={s.status}>{S.status}</div>}
            {S && (
              <div className={s.transport}>
                <div className={s.row}>
                  <button
                    className={s.round}
                    aria-label={S.playing ? "Pause workflow" : "Play workflow"}
                    onClick={() => E?.togglePlay()}
                  >
                    {S.playing ? <Pause size={15} /> : <Play size={15} />}
                  </button>
                  <input
                    type="range"
                    aria-label="Workflow time"
                    min={0}
                    max={10000}
                    value={Math.round((S.t / S.total) * 10000)}
                    onChange={(e) =>
                      E?.seek((+e.target.value / 10000) * S.total)
                    }
                  />
                  <span className={s.time}>
                    {S.t.toFixed(0)} / {S.total.toFixed(0)} s
                  </span>
                  <select
                    aria-label="Playback rate"
                    value={rate}
                    onChange={(e) => {
                      setRate(+e.target.value);
                      E?.setRate(+e.target.value);
                    }}
                  >
                    {[1, 4, 8, 16].map((r) => (
                      <option key={r} value={r}>
                        {r}×
                      </option>
                    ))}
                  </select>
                </div>
                <div className={s.lanes} aria-hidden="true">
                  {(["flex", "ot2", "ur", "bal"] as const).map((lane, k) => (
                    <div key={lane} className={s.lane} style={{ top: k * 6.5 }}>
                      {S.stages
                        .filter((x) => x.lane === lane && x.t1 > x.t0)
                        .map((x) => (
                          <b
                            key={x.label}
                            style={{
                              left: `${(x.t0 / S.total) * 100}%`,
                              width: `${Math.max(0.4, ((x.t1 - x.t0) / S.total) * 100)}%`,
                              background: LANE[lane][1],
                            }}
                          />
                        ))}
                    </div>
                  ))}
                  <div
                    className={s.cursor}
                    style={{ left: `${(S.t / S.total) * 100}%` }}
                  />
                </div>
              </div>
            )}
          </div>

          {S && (
            <section className={s.panel}>
              <div className={s.editor}>
                <div>
                  <div className={s.panelHead}>
                    <h2>UR5e joints</h2>
                    <div className={s.row}>
                      <button
                        className={s.ghost}
                        disabled={!S.canUndo}
                        onClick={() => E?.undo()}
                      >
                        Undo pose edit
                      </button>
                      <button
                        aria-pressed={S.gripClosed}
                        onClick={() => E?.toggleGripper()}
                      >
                        {S.gripClosed ? "Gripper closed" : "Gripper open"}
                      </button>
                    </div>
                  </div>
                  <div className={s.joints}>
                    {NAMES.map((n, j) => (
                      <div
                        key={n}
                        className={`${s.joint} ${S.joint === j ? s.jointSel : ""}`}
                        onPointerDown={() => S.joint !== j && E?.selectJoint(j)}
                      >
                        <span className={s.jn}>
                          <i style={{ background: `var(--j${j + 1})` }} />J
                          {j + 1}
                          <small>{n}</small>
                        </span>
                        <input
                          type="range"
                          aria-label={`J${j + 1} ${n} angle`}
                          min={-LIMIT_DEG[j] + 0.1}
                          max={LIMIT_DEG[j] - 0.1}
                          step={0.1}
                          value={S.pose[j]}
                          onPointerDown={() => E?.setJoint(j, S.pose[j])}
                          onChange={(e) =>
                            E?.setJoint(j, +e.target.value, true)
                          }
                        />
                        <input
                          type="number"
                          aria-label={`J${j + 1} ${n} degrees`}
                          step={0.1}
                          value={(+S.pose[j]).toFixed(1)}
                          onChange={(e) => E?.setJoint(j, +e.target.value)}
                        />
                      </div>
                    ))}
                  </div>
                  <p className={s.note}>
                    Drag the ring in the view to turn the selected joint; Shift
                    slows it.
                  </p>
                </div>
                <div className={s.tools}>
                  <div>
                    <p className={s.sub}>Move tool to</p>
                    <div className={s.targets}>
                      {targets.map((t, i) => (
                        <button key={t.label} onClick={() => E?.moveTo(i)}>
                          {t.label}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div>
                    <p className={s.sub}>Jog tool · 1 cm</p>
                    <div className={s.jog}>
                      {(
                        [
                          ["", null],
                          ["Y+", [0, 0.01, 0]],
                          ["Z+", [0, 0, 0.01]],
                          ["X−", [-0.01, 0, 0]],
                          ["Y−", [0, -0.01, 0]],
                          ["X+", [0.01, 0, 0]],
                          ["", null],
                          ["", null],
                          ["Z−", [0, 0, -0.01]],
                        ] as [string, [number, number, number] | null][]
                      ).map(([l, d], i) =>
                        d ? (
                          <button key={i} onClick={() => E?.jog(d)}>
                            {l}
                          </button>
                        ) : (
                          <span key={i} />
                        ),
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </section>
          )}

          {S && (
            <div className={s.two}>
              <section className={s.panel}>
                <div className={s.panelHead}>
                  <h2>Instruments now</h2>
                  <span className={s.time}>t = {S.t.toFixed(1)} s</span>
                </div>
                <div
                  className={`${s.scale} ${S.balance.stable ? "" : s.unstable}`}
                  data-testid="balance-reading"
                >
                  <span>{S.balance.text}</span>
                  <small>{S.balance.note}</small>
                </div>
                <div className={s.devices}>
                  <div>
                    <b>Flex</b>
                    <span>{S.devices.flex}</span>
                  </div>
                  <div>
                    <b>OT-2</b>
                    <span>{S.devices.ot2}</span>
                  </div>
                  <div>
                    <b>UR5e</b>
                    <span>{S.devices.ur}</span>
                  </div>
                </div>
              </section>
              <section className={s.panel}>
                <div className={s.panelHead}>
                  <h2>Sample vials</h2>
                  <span className={s.time}>{S.rack}</span>
                </div>
                <div className={s.tableWrap}>
                  <table className={s.vials}>
                    <thead>
                      <tr>
                        <th>Vial</th>
                        <th>µL</th>
                        <th>Solvent</th>
                        <th>Substrate</th>
                        <th>Reagent</th>
                        <th>Catalyst</th>
                        <th>mg</th>
                      </tr>
                    </thead>
                    <tbody>
                      {S.vials.map((v) => (
                        <tr key={v.well}>
                          <td>
                            <i
                              style={{
                                background:
                                  v.total > 1
                                    ? `rgb(${v.rgb.map((x) => Math.round(x * 255)).join(",")})`
                                    : "transparent",
                              }}
                            />
                            {v.well}
                          </td>
                          <td>{v.total.toFixed(0)}</td>
                          <td>{v.solvent.toFixed(0)}</td>
                          <td>{v.substrate.toFixed(0)}</td>
                          <td>{v.reagent.toFixed(0)}</td>
                          <td>{v.catalyst.toFixed(0)}</td>
                          <td>{v.mg.toFixed(0)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </div>
          )}

          {S && (
            <section className={s.panel}>
              <div className={s.panelHead}>
                <h2>UR5e six-axis excursion</h2>
                <div className={s.row}>
                  {NAMES.map((n, j) => (
                    <span key={n} className={s.key}>
                      <i style={{ background: `var(--j${j + 1})` }} />J{j + 1}
                    </span>
                  ))}
                </div>
              </div>
              <div className={s.chart}>
                <canvas
                  ref={chartRef}
                  onPointerDown={(e) => {
                    if (!chart?.total) return;
                    const r = e.currentTarget.getBoundingClientRect();
                    E?.seekArm(
                      Math.max(
                        0,
                        Math.min(
                          chart.total,
                          ((e.clientX - r.left - 40) / (r.width - 48)) *
                            chart.total,
                        ),
                      ),
                    );
                  }}
                />
              </div>
            </section>
          )}

          {def && (
            <details className={s.panel}>
              <summary>Registered assets ({def.assets.length})</summary>
              <div className={s.tableWrap}>
                <table className={s.assets}>
                  <thead>
                    <tr>
                      <th>Asset</th>
                      <th>Kind</th>
                      <th>Licence</th>
                      <th>Source</th>
                      <th>SHA-256</th>
                    </tr>
                  </thead>
                  <tbody>
                    {def.assets.map((a) => (
                      <tr key={a.id}>
                        <td>
                          <b>{a.name}</b>
                          <small>{a.notes}</small>
                        </td>
                        <td>{a.kind}</td>
                        <td>{a.license}</td>
                        <td>
                          {a.sources.map((x) => (
                            <div key={x.repository}>
                              {x.repository}
                              {x.commit ? `@${x.commit.slice(0, 7)}` : ""}
                            </div>
                          ))}
                        </td>
                        <td className={s.mono}>
                          {a.sha256 ? a.sha256.slice(0, 12) : "drawn in code"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className={s.note}>
                Every file is checked against its registered digest before the
                scene loads. Volumes, densities, masses and balance readings are
                illustrative; clearance covers arm links, fingers and the
                carried rack against modelled walls, decks and labware only.
              </p>
            </details>
          )}
        </div>

        <aside className={s.side}>
          <div className={s.panel}>
            <div className={s.tabs} role="tablist">
              <button
                role="tab"
                aria-selected={tab === "flow"}
                onClick={() => setTab("flow")}
              >
                Workflow
              </button>
              <button
                role="tab"
                aria-selected={tab === "chain"}
                onClick={() => setTab("chain")}
              >
                Arm chain{" "}
                <span className={s.time}>
                  {S ? `${S.chain.length}/24` : ""}
                </span>
              </button>
            </div>
            {S && tab === "flow" && (
              <div className={s.stages}>
                {S.stages.map((x) => {
                  const [, what] = x.label.split(" · ");
                  return (
                    <button
                      key={x.label}
                      className={`${s.stageRow} ${s[x.status]}`}
                      onClick={() => E?.seek(x.t0 + 0.01)}
                    >
                      <i style={{ background: LANE[x.lane][1] }} />
                      <span>
                        <b>{what}</b>
                        <small>{x.sub}</small>
                      </span>
                      <span className={s.time}>
                        {x.t0.toFixed(0)}–{x.t1.toFixed(0)} s
                      </span>
                    </button>
                  );
                })}
                <div className={`${s.msg} ${s[S.flowMsg.level]}`}>
                  {S.flowMsg.text}
                </div>
              </div>
            )}
            {S && tab === "chain" && (
              <div className={s.chainPane}>
                <div className={s.compose}>
                  <label>
                    Name
                    <input
                      value={form.name}
                      onChange={(e) =>
                        setForm({ ...form, name: e.target.value })
                      }
                    />
                  </label>
                  <label>
                    Hold (s)
                    <input
                      type="number"
                      min={0}
                      max={10}
                      step={0.5}
                      value={form.hold}
                      onChange={(e) =>
                        setForm({ ...form, hold: +e.target.value })
                      }
                    />
                  </label>
                  <label>
                    Gripper
                    <select
                      value={form.grip}
                      onChange={(e) =>
                        setForm({ ...form, grip: e.target.value })
                      }
                    >
                      <option value="">No change</option>
                      <option value="close">Close</option>
                      <option value="open">Open</option>
                    </select>
                  </label>
                </div>
                <div className={s.row}>
                  <button
                    className={s.primary}
                    disabled={S.chain.length >= 24}
                    onClick={() => E?.addWaypoint(wp())}
                  >
                    Add waypoint
                  </button>
                  <button
                    disabled={S.sel < 0}
                    onClick={() => E?.updateWaypoint(wp())}
                  >
                    Update selected
                  </button>
                  <button onClick={() => E?.regenerate()}>Regenerate</button>
                  <button className={s.ghost} onClick={() => E?.clear()}>
                    Clear
                  </button>
                </div>
                <label className={s.speed}>
                  <span>
                    Motion speed <b className={s.time}>{S.speed} °/s</b>
                  </span>
                  <input
                    type="range"
                    min={1}
                    max={40}
                    value={S.speed}
                    onChange={(e) => E?.setSpeed(+e.target.value)}
                  />
                </label>
                <div className={s.summary}>
                  <div>
                    <b>{S.plan ? S.plan.total.toFixed(1) : "–"}</b>
                    <span>Arm time, s</span>
                  </div>
                  <div>
                    <b>{S.plan ? S.plan.peakV.toFixed(1) : "–"}</b>
                    <span>Peak joint °/s</span>
                  </div>
                  <div>
                    <b className={S.plan?.hitSeconds ? s.badText : ""}>
                      {S.plan
                        ? S.plan.hitSeconds
                          ? `${S.plan.hitSeconds.toFixed(2)} s`
                          : "0"
                        : "–"}
                    </b>
                    <span>Clearance hits</span>
                  </div>
                </div>
                <div
                  className={`${s.msg} ${s[(S.message ?? S.planMsg).level]}`}
                >
                  {(S.message ?? S.planMsg).text}
                </div>
                <div className={s.row}>
                  <button
                    disabled={!S.plan || S.plan.total > 180 || simulating}
                    onClick={async () => {
                      const path = E?.armPath();
                      if (!E || !path) return;
                      const key = E.exportJSON();
                      setSimulating(true);
                      try {
                        const result = await api<ArmSimulation>(
                          "/workcell/arm-path/simulate",
                          body(path),
                        );
                        setSim({ ...result, key });
                        if (result.collision && E.exportJSON() === key)
                          E.seekArm(result.collision.at_s);
                      } catch {
                        E.flash(
                          "The arm simulation did not answer. Try again.",
                        );
                      } finally {
                        setSimulating(false);
                      }
                    }}
                  >
                    {simulating ? "Simulating…" : "Simulate in MuJoCo"}
                  </button>
                </div>
                {sim && sim.key === E?.exportJSON() && (
                  <div
                    role="status"
                    className={`${s.msg} ${sim.problem ? s.bad : s.ok}`}
                  >
                    {sim.problem
                      ? `In simulation: ${sim.problem}.`
                      : `Simulated in MuJoCo ${sim.version}: ${sim.seconds.toFixed(1)} s · ${Math.round(sim.torque_ratio * 100)}% joint torque · ${(sim.clearance_m * 100).toFixed(1)} cm ${sim.nearest ? `from ${sim.nearest}` : "clear"} · ${sim.payload_kg} kg load. Not run on a robot.`}
                  </div>
                )}
                <div className={s.chain}>
                  {S.chain.slice(0, S.visible).map((w, i) => (
                    <div
                      key={i}
                      role="button"
                      tabIndex={0}
                      className={`${s.wp} ${i === S.sel ? s.wpSel : ""} ${i === S.current ? s.wpNow : ""}`}
                      onClick={() => {
                        setForm({
                          name: w.name,
                          hold: w.hold,
                          grip: w.grip ?? "",
                        });
                        E?.selectWaypoint(i);
                      }}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          setForm({
                            name: w.name,
                            hold: w.hold,
                            grip: w.grip ?? "",
                          });
                          E?.selectWaypoint(i);
                        }
                      }}
                    >
                      <span className={s.idx}>
                        {String(i + 1).padStart(2, "0")}
                      </span>
                      <div className={s.wpBody}>
                        <b>{w.name}</b>
                        <span className={s.deg}>
                          {w.degrees
                            .map((v) => `${(+v).toFixed(1)}°`)
                            .join(" / ")}
                        </span>
                        <span className={s.meta}>
                          <em>
                            Travel{" "}
                            {w.travel === null
                              ? "–"
                              : `${w.travel.toFixed(2)} s`}
                          </em>
                          {w.hold ? <em>Hold {w.hold} s</em> : null}
                          {w.grip ? (
                            <em className={w.grip === "close" ? s.okChip : ""}>
                              {w.grip === "close"
                                ? "Close gripper"
                                : "Open gripper"}
                            </em>
                          ) : null}
                          {w.issues.map((x) => (
                            <em
                              key={x.text}
                              className={
                                x.level === "bad" ? s.badChip : s.warnChip
                              }
                            >
                              {x.text}
                            </em>
                          ))}
                        </span>
                      </div>
                      <span
                        className={s.acts}
                        onClick={(e) => e.stopPropagation()}
                      >
                        <button
                          aria-label="Move up"
                          disabled={i === 0}
                          onClick={() => E?.moveWaypoint(i, -1)}
                        >
                          ↑
                        </button>
                        <button
                          aria-label="Move down"
                          disabled={i === S.chain.length - 1}
                          onClick={() => E?.moveWaypoint(i, 1)}
                        >
                          ↓
                        </button>
                        <button
                          aria-label="Duplicate"
                          onClick={() => E?.duplicateWaypoint(i)}
                        >
                          ⧉
                        </button>
                        <button
                          aria-label="Delete"
                          onClick={() => E?.deleteWaypoint(i)}
                        >
                          ✕
                        </button>
                      </span>
                    </div>
                  ))}
                </div>
                <details>
                  <summary>
                    Export or import <code>ur5e.action-chain/2</code>
                  </summary>
                  <div className={s.row}>
                    <button
                      onClick={async () => {
                        const t = E?.exportJSON() ?? "";
                        setJson(t);
                        try {
                          await navigator.clipboard.writeText(t);
                          E?.flash("Copied ur5e.action-chain/2 JSON.", "ok");
                        } catch {
                          E?.flash(
                            "Clipboard unavailable. Copy the JSON below.",
                            "warn",
                          );
                        }
                      }}
                    >
                      Copy JSON
                    </button>
                    <button onClick={() => E?.importJSON(json)}>
                      Load pasted JSON
                    </button>
                  </div>
                  <textarea
                    aria-label="Action chain JSON"
                    spellCheck={false}
                    value={json || E?.exportJSON() || ""}
                    onChange={(e) => setJson(e.target.value)}
                  />
                  <p className={s.note}>
                    Matches the UR5e connector's PrepareActionChainAtSpeed
                    input; gripper steps are kept in waypoint names.
                  </p>
                </details>
              </div>
            )}
          </div>
          <section className={`${s.panel} ${s.log}`} aria-label="Run log">
            <div className={s.panelHead}>
              <h2>Run log</h2>
              <span className={s.time}>
                {S ? `${S.log.length} entries` : ""}
              </span>
            </div>
            <div
              className={s.logList}
              ref={logRef}
              role="log"
              data-testid="run-log"
            >
              {S?.log.map((e, i) => (
                <div key={i} className={s.logRow}>
                  <span className={s.time}>{e.stamp}</span>
                  <span className={s.logDev} style={{ color: LANE[e.dev][1] }}>
                    {LANE[e.dev][0]}
                  </span>
                  <span>{e.text}</span>
                </div>
              ))}
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}

function drawChart(
  canvas: HTMLCanvasElement | null,
  data: ChartData | null,
  joint: number,
  tokens: HTMLElement | null,
) {
  if (!canvas || !tokens) return;
  const css = (n: string) =>
    getComputedStyle(tokens).getPropertyValue(n).trim();
  const r = canvas.getBoundingClientRect(),
    dpr = Math.min(window.devicePixelRatio, 2);
  if (!r.width) return;
  canvas.width = r.width * dpr;
  canvas.height = r.height * dpr;
  const cx = canvas.getContext("2d")!;
  cx.setTransform(dpr, 0, 0, dpr, 0, 0);
  cx.clearRect(0, 0, r.width, r.height);
  if (!data?.total) return;
  const L = 40,
    R = 8,
    T = 8,
    B = 20,
    w = r.width - L - R,
    h = r.height - T - B;
  let lo = Infinity,
    hi = -Infinity;
  for (const [, q] of data.samples)
    for (const v of q) ((lo = Math.min(lo, v)), (hi = Math.max(hi, v)));
  lo = Math.floor(lo / 90) * 90;
  hi = Math.ceil(hi / 90) * 90;
  if (hi === lo) hi = lo + 90;
  const X = (t: number) => L + (t / data.total) * w,
    Y = (v: number) => T + (1 - (v - lo) / (hi - lo)) * h;
  cx.font = "11px ui-monospace, monospace";
  cx.fillStyle = css("--muted");
  cx.strokeStyle = css("--line");
  cx.lineWidth = 1;
  for (let v = lo; v <= hi; v += 90) {
    cx.beginPath();
    cx.moveTo(L, Y(v));
    cx.lineTo(L + w, Y(v));
    cx.stroke();
    cx.textAlign = "right";
    cx.fillText(`${v}°`, L - 6, Y(v) + 4);
  }
  cx.textAlign = "center";
  for (let t = 0; t <= data.total; t += data.total > 60 ? 20 : 10)
    cx.fillText(`${t}s`, X(t), r.height - 5);
  cx.strokeStyle = css("--line-strong");
  cx.setLineDash([2, 3]);
  for (const a of data.arrive) {
    cx.beginPath();
    cx.moveTo(X(a), T);
    cx.lineTo(X(a), T + h);
    cx.stroke();
  }
  cx.setLineDash([]);
  cx.fillStyle = css("--danger-soft");
  for (const t of data.hits)
    cx.fillRect(X(t) - 1, T, Math.max(2, (0.05 / data.total) * w), h);
  for (let j = 0; j < 6; j++) {
    cx.strokeStyle = css(`--j${j + 1}`);
    cx.lineWidth = j === joint ? 2.4 : 1.4;
    cx.globalAlpha = j === joint ? 1 : 0.75;
    cx.beginPath();
    data.samples.forEach(([t, q], k) =>
      k ? cx.lineTo(X(t), Y(q[j])) : cx.moveTo(X(t), Y(q[j])),
    );
    cx.stroke();
  }
  cx.globalAlpha = 1;
  if (data.cursor !== null) {
    cx.strokeStyle = css("--ink");
    cx.lineWidth = 1.2;
    cx.beginPath();
    cx.moveTo(X(data.cursor), T);
    cx.lineTo(X(data.cursor), T + h);
    cx.stroke();
  }
}
