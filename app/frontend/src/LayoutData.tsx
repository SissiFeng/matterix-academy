import { Pause, Play } from "lucide-react";
import {
  DEFAULT_SAMPLE,
  operationLabels,
  type LayoutPreview,
  type Twin,
} from "./instrumentTypes";
import { armAt, duration, stateAt, stepAt } from "./layoutTimeline";
import s from "./LayoutData.module.css";

const JOINTS = [
  ["J1", "Base", "#2f7fa8"],
  ["J2", "Shoulder", "#c2552d"],
  ["J3", "Elbow", "#3d8a5f"],
  ["J4", "Wrist 1", "#8a5fc2"],
  ["J5", "Wrist 2", "#c29a2d"],
  ["J6", "Wrist 3", "#6b7480"],
] as const;
const RATES = [1, 4, 8, 16];
const deg = (rad: number) => (rad * 180) / Math.PI;

/**
 * The planned workflow in time: who works when, what the arm's joints are doing, and
 * where every sample is. The clock belongs to the page, so the 3D view follows it.
 */
export default function LayoutData({
  twins,
  preview,
  clock,
  onClock,
  playing,
  onPlaying,
  rate,
  onRate,
}: {
  twins: Twin[];
  preview: LayoutPreview;
  clock: number;
  onClock: (seconds: number) => void;
  playing: boolean;
  onPlaying: (playing: boolean) => void;
  rate: number;
  onRate: (rate: number) => void;
}) {
  const timeline = preview.timeline ?? [];
  const total = duration(timeline);
  if (!timeline.length || !total) return null;
  const name = (id: string | null) =>
    twins.find((t) => t.id === id)?.spec?.name ?? "—";
  const now = stepAt(timeline, clock);
  const devices = [...new Set(timeline.map((step) => step.device_id))];
  const moment = armAt(preview, clock);
  const joints = moment?.motion.joints[moment.frame];
  const tip = moment?.motion.frames[moment.frame]?.at(-1);
  const profile = moment?.motion.profile;
  const state = stateAt(timeline, clock);
  const carried =
    timeline[now].operation === "transfer" && clock < timeline[now].end_s
      ? timeline[now]
      : null;
  const series = moment ? moment.motion.joints : [];
  const at = (i: number) =>
    profile?.progress[i] ?? i / Math.max(1, series.length - 1);

  return (
    <section className={s.data} aria-label="Workflow timeline">
      <div className={s.transport}>
        <button
          className={s.play}
          aria-label={playing ? "Pause workflow" : "Play workflow"}
          onClick={() => {
            if (!playing && clock >= total) onClock(0);
            onPlaying(!playing);
          }}
        >
          {playing ? <Pause size={15} /> : <Play size={15} />}
        </button>
        <input
          type="range"
          aria-label="Workflow time"
          min={0}
          max={total}
          step={0.1}
          value={Math.min(clock, total)}
          onChange={(e) => onClock(Number(e.target.value))}
        />
        <span className={s.time}>
          {clock.toFixed(1)} / {total.toFixed(1)} s
        </span>
        <select
          aria-label="Playback rate"
          value={rate}
          onChange={(e) => onRate(Number(e.target.value))}
        >
          {RATES.map((r) => (
            <option key={r} value={r}>
              {r}×
            </option>
          ))}
        </select>
      </div>
      <div className={s.lanes}>
        {devices.map((id) => (
          <Lane key={id} label={name(id)}>
            {timeline.map(
              (step, i) =>
                step.device_id === id && (
                  <i
                    key={step.step}
                    className={s.bar}
                    data-operation={step.operation}
                    data-active={i === now}
                    title={`Step ${step.step} · ${operationLabels[step.operation]} · ${step.start_s}–${step.end_s} s`}
                    style={{
                      left: `${(step.start_s / total) * 100}%`,
                      width: `${((step.end_s - step.start_s) / total) * 100}%`,
                    }}
                  />
                ),
            )}
            <i
              className={s.head}
              style={{ left: `${(clock / total) * 100}%` }}
            />
          </Lane>
        ))}
      </div>

      <div className={s.columns}>
        {moment && joints && (
          <div className={s.card} role="group" aria-label="Arm joints">
            <h3>{moment.motion.arm} joints</h3>
            <div className={s.joints}>
              {JOINTS.map(([key, label, color], i) => (
                <Joint
                  key={key}
                  name={`${key} ${label}`}
                  color={color}
                  value={deg(joints[i])}
                />
              ))}
            </div>
            <svg
              className={s.chart}
              viewBox="0 0 100 100"
              preserveAspectRatio="none"
              role="img"
              aria-label={`Joint angles over step ${moment.motion.step}`}
            >
              {JOINTS.map(([key, , color], j) => (
                <polyline
                  key={key}
                  stroke={color}
                  points={series
                    .map(
                      (q, i) =>
                        `${(at(i) * 100).toFixed(2)},${(50 - (deg(q[j]) / 360) * 96).toFixed(2)}`,
                    )
                    .join(" ")}
                />
              ))}
              <line
                x1={at(moment.frame) * 100}
                x2={at(moment.frame) * 100}
                y1={0}
                y2={100}
              />
            </svg>
            <dl className={s.facts}>
              <dt>Doing</dt>
              <dd>
                {moment.moving
                  ? (profile?.segments[profile.segment[moment.frame]] ??
                    `Step ${moment.motion.step}`)
                  : "Waiting"}
              </dd>
              {tip && (
                <>
                  <dt>Tool point</dt>
                  <dd>
                    x {(tip[0] * 1000).toFixed(0)} · y{" "}
                    {(tip[1] * 1000).toFixed(0)} · z{" "}
                    {(tip[2] * 1000).toFixed(0)} mm
                  </dd>
                </>
              )}
              {profile && (
                <>
                  <dt>Clearance</dt>
                  <dd>
                    {(profile.clearance_m[moment.frame] * 100).toFixed(1)} cm to{" "}
                    {profile.nearest[moment.frame]}
                  </dd>
                </>
              )}
            </dl>
          </div>
        )}

        <div className={s.card}>
          <h3>Run log</h3>
          <ol className={s.log} aria-label="Run log">
            {timeline.map((step, i) => (
              <li
                key={step.step}
                data-state={i === now ? "now" : i < now ? "done" : "later"}
              >
                <time>
                  {step.start_s.toFixed(1)}–{step.end_s.toFixed(1)} s
                </time>
                <span>
                  {name(step.device_id)} ·{" "}
                  {operationLabels[step.operation].toLowerCase()}
                  {step.operation === "transfer"
                    ? ` to ${name(step.location)}`
                    : ""}
                  {step.site ? ` · slot ${step.site}` : ""}
                  {step.sample !== DEFAULT_SAMPLE ? ` · ${step.sample}` : ""}
                </span>
              </li>
            ))}
          </ol>
        </div>

        <div className={s.card}>
          <h3>Samples</h3>
          {state || carried ? (
            <table className={s.samples}>
              <thead>
                <tr>
                  <th>Sample</th>
                  <th>Where</th>
                  <th>µL</th>
                  <th>°C</th>
                  <th>Mixed</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries((state ?? carried!).samples).map(
                  ([key, sample]) => (
                    <tr key={key}>
                      <td>{key}</td>
                      <td>
                        {carried?.sample === key
                          ? `carried by ${name(carried.device_id)}`
                          : `${name(sample.location)}${sample.site ? ` · ${sample.site}` : ""}`}
                      </td>
                      <td>{sample.volume_ul}</td>
                      <td>{sample.temperature_c}</td>
                      <td>{sample.mixed ? "yes" : "no"}</td>
                    </tr>
                  ),
                )}
              </tbody>
            </table>
          ) : (
            <p className={s.time}>No sample loaded yet.</p>
          )}
          {state &&
            Object.entries(state.consumables).map(([id, items]) => (
              <dl key={id} className={s.facts}>
                {Object.entries(items).map(([item, left]) => (
                  <FactRow key={item} label={`${name(id)} · ${item}`}>
                    {left} left
                  </FactRow>
                ))}
              </dl>
            ))}
        </div>
      </div>
    </section>
  );
}

function Lane({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <>
      <span>{label}</span>
      <div className={s.track}>{children}</div>
    </>
  );
}

function Joint({
  name,
  color,
  value,
}: {
  name: string;
  color: string;
  value: number;
}) {
  return (
    <>
      <span>
        <i className={s.dot} style={{ background: color }} />
        {name}
      </span>
      <meter min={-360} max={360} value={value} aria-label={name} />
      <output>{value.toFixed(1)}°</output>
    </>
  );
}

function FactRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </>
  );
}
