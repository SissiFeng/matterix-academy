import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowRight, CircleAlert, RefreshCw, Square } from "lucide-react";
import { api, json } from "./api";
import type { Device } from "./workcellTypes";
import s from "./PhysicalRuns.module.css";

type Side = {
  status: string;
  error: string;
  observation: { source: string } | null;
  reported_by?: string;
} | null;
type Step = {
  operation: { operation_id: string; action: string };
  sim: Side;
  real: Side;
  gate: "passed" | "held" | null;
  comparisons: { field: string; status: string; reason: string }[];
};
export type PairRun = {
  run_id: string;
  version: number;
  mode: "sim_only" | "real_only" | "sim_first" | "paired" | "predict";
  status: string;
  reason: string;
  requested_as: string;
  instrument_id: string;
  steps: Step[];
  completed_steps: number;
  total_steps: number;
  approval: { by: string; at: number } | null;
  created_at: number;
};
type Status = {
  pairing_enabled: boolean;
  real_enabled: boolean;
  operator: boolean;
};
type Gateway = {
  online: boolean;
  fault: string;
  inspected: boolean;
  pending: number;
};

const modes: { value: PairRun["mode"]; label: string; detail: string }[] = [
  {
    value: "sim_only",
    label: "Rehearse in the twin",
    detail: "Simulation only. No hardware.",
  },
  {
    value: "sim_first",
    label: "Twin first, then real",
    detail: "Each real step waits for its twin prediction.",
  },
  {
    value: "paired",
    label: "Paired",
    detail: "Twin and real run each step together and are compared.",
  },
  {
    value: "real_only",
    label: "Real only",
    detail: "Physical steps without a twin prediction.",
  },
];
const ACTIVE = new Set(["queued", "running", "awaiting_approval"]);
const label = (value: string) => value.replaceAll("_", " ");

function SideCell({ side, kind }: { side: Side; kind: "Twin" | "Real" }) {
  if (!side) return <td>Not run</td>;
  return (
    <td data-state={side.status}>
      <strong>{label(side.status)}</strong>
      <span>
        {kind === "Twin"
          ? "Simulated"
          : side.reported_by
            ? `Reported by ${side.reported_by}`
            : "Physical"}
        {side.observation ? ` · ${side.observation.source}` : ""}
      </span>
      {side.error && <small>{side.error}</small>}
    </td>
  );
}

export default function PhysicalRuns({ device }: { device: Device }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [runs, setRuns] = useState<PairRun[]>([]);
  const [gateway, setGateway] = useState<Gateway | null>(null);
  const [mode, setMode] = useState<PairRun["mode"]>("sim_only");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirmation, setConfirmation] = useState({
    deck_matches_plan: false,
    workspace_clear: false,
    emergency_stop_reachable: false,
    note: "",
  });
  const [reconcileNote, setReconcileNote] = useState("");
  const alive = useRef(true);
  const instrument = device.instrument_id;

  const load = useCallback(async () => {
    if (!instrument) return;
    try {
      const current = await api<Status>("/sim2real/status");
      const list = current.operator
        ? await api<PairRun[]>(
            `/pair-runs?instrument_id=${encodeURIComponent(instrument)}`,
          )
        : await api<PairRun[]>(`/devices/${device.id}/pair-runs`);
      const detail = current.operator
        ? await api<{ gateway: Gateway }>(
            `/instruments/${encodeURIComponent(instrument)}`,
          )
        : null;
      if (!alive.current) return;
      setStatus(current);
      setRuns(list);
      setGateway(detail?.gateway ?? null);
      setError("");
    } catch (reason) {
      if (alive.current)
        setError(
          reason instanceof Error ? reason.message : "Could not load runs",
        );
    }
  }, [device.id, instrument]);

  useEffect(() => {
    alive.current = true;
    void load();
    return () => {
      alive.current = false;
    };
  }, [load]);
  const active = runs.some((run) => ACTIVE.has(run.status));
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => void load(), 2000);
    return () => window.clearInterval(timer);
  }, [active, load]);

  const act = async (work: () => Promise<unknown>) => {
    setBusy(true);
    setError("");
    try {
      await work();
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The request could not be completed.",
      );
    } finally {
      if (alive.current) setBusy(false);
    }
  };

  if (!instrument)
    return (
      <section className={s.panel}>
        <h2>03 / Physical runs</h2>
        <p>
          No physical instrument is linked to this declaration. A lab operator
          links a registered instrument after its gateway and connector identity
          have been reviewed.
        </p>
      </section>
    );
  if (status && !status.pairing_enabled)
    return (
      <section className={s.panel}>
        <h2>03 / Physical runs</h2>
        <p>Sim-to-real runs are not enabled in this deployment.</p>
      </section>
    );
  const confirmed =
    confirmation.deck_matches_plan &&
    confirmation.workspace_clear &&
    confirmation.emergency_stop_reachable &&
    confirmation.note.trim().length >= 8;
  const realMode = mode !== "sim_only";

  return (
    <section className={s.panel} aria-labelledby="physical-runs">
      <div className={s.heading}>
        <h2 id="physical-runs">03 / Physical runs · {instrument}</h2>
        <button
          className={s.icon}
          onClick={() => void load()}
          aria-label="Refresh physical runs"
        >
          <RefreshCw size={16} />
        </button>
      </div>
      {error && (
        <p className={s.alert} role="alert">
          <CircleAlert size={16} /> {error}
        </p>
      )}
      {gateway && (
        <div
          className={s.gateway}
          data-state={
            gateway.fault ? "held" : gateway.online ? "online" : "offline"
          }
        >
          <strong>
            Gateway{" "}
            {gateway.fault ? "held" : gateway.online ? "online" : "offline"}
            {gateway.inspected ? " · connector verified" : ""}
          </strong>
          {gateway.fault && <p>{gateway.fault}</p>}
          {gateway.fault && (
            <div className={s.inline}>
              <input
                aria-label="Reconciliation note"
                placeholder="What did you verify on the instrument?"
                value={reconcileNote}
                maxLength={500}
                onChange={(e) => setReconcileNote(e.target.value)}
              />
              <button
                className={s.secondary}
                disabled={
                  busy || reconcileNote.trim().length < 8 || !gateway.online
                }
                onClick={() =>
                  void act(() =>
                    api(
                      `/instruments/${encodeURIComponent(instrument)}/reconcile`,
                      json({ note: reconcileNote }),
                    ),
                  )
                }
              >
                Record reconciliation
              </button>
            </div>
          )}
        </div>
      )}
      <fieldset className={s.modes}>
        <legend>Request a run of the registered workflow</legend>
        {modes.map((option) => (
          <label key={option.value} data-selected={mode === option.value}>
            <input
              type="radio"
              name="pair-mode"
              value={option.value}
              checked={mode === option.value}
              disabled={
                busy ||
                (option.value !== "sim_only" && status?.real_enabled === false)
              }
              onChange={() => setMode(option.value)}
            />
            <strong>{option.label}</strong>
            <span>{option.detail}</span>
          </label>
        ))}
      </fieldset>
      <div className={s.inline}>
        <button
          className={s.primary}
          disabled={busy || !status}
          onClick={() =>
            void act(() =>
              api(
                "/pair-runs",
                json({
                  run_id: crypto.randomUUID(),
                  instrument_id: instrument,
                  mode,
                }),
              ),
            )
          }
        >
          {realMode ? "Request supervised run" : "Run in the twin"}{" "}
          <ArrowRight size={16} />
        </button>
        <small>
          {realMode
            ? "A lab operator must approve and confirm the physical site before anything moves."
            : "Simulation evidence only; it never authorizes hardware."}
        </small>
      </div>
      {runs.length === 0 ? (
        <p className={s.empty}>No runs on this instrument yet.</p>
      ) : (
        runs.map((run) => (
          <article key={run.run_id} className={s.run} data-status={run.status}>
            <header>
              <div>
                <strong>
                  {modes.find((m) => m.value === run.mode)?.label ??
                    label(run.mode)}
                </strong>
                <span>
                  {label(run.status)} · {run.completed_steps} /{" "}
                  {run.total_steps} steps ·{" "}
                  {new Date(run.created_at * 1000).toLocaleString()}
                </span>
                {run.reason && <small>{run.reason}</small>}
              </div>
              {(run.status === "running" ||
                run.status === "queued" ||
                run.status === "awaiting_approval") && (
                <button
                  className={s.secondary}
                  disabled={busy}
                  onClick={() =>
                    void act(() =>
                      api(
                        `/pair-runs/${run.run_id}/stop`,
                        json({ expected_version: run.version }),
                      ),
                    )
                  }
                >
                  <Square size={14} />{" "}
                  {run.status === "awaiting_approval"
                    ? "Cancel"
                    : "Request stop"}
                </button>
              )}
            </header>
            {run.status === "awaiting_approval" && status?.operator && (
              <div className={s.approval}>
                <strong>Operator approval</strong>
                {(
                  [
                    [
                      "deck_matches_plan",
                      "The deck matches this plan's labware and tips",
                    ],
                    [
                      "workspace_clear",
                      "The workspace is clear of people and loose objects",
                    ],
                    [
                      "emergency_stop_reachable",
                      "The emergency stop is within reach",
                    ],
                  ] as const
                ).map(([key, text]) => (
                  <label key={key}>
                    <input
                      type="checkbox"
                      checked={confirmation[key]}
                      onChange={(e) =>
                        setConfirmation((c) => ({
                          ...c,
                          [key]: e.target.checked,
                        }))
                      }
                    />
                    {text}
                  </label>
                ))}
                <input
                  aria-label="Approval note"
                  placeholder="Note for the run record"
                  value={confirmation.note}
                  maxLength={500}
                  onChange={(e) =>
                    setConfirmation((c) => ({ ...c, note: e.target.value }))
                  }
                />
                <div className={s.inline}>
                  <button
                    className={s.primary}
                    disabled={busy || !confirmed}
                    onClick={() =>
                      void act(() =>
                        api(
                          `/pair-runs/${run.run_id}/approve`,
                          json({ expected_version: run.version, confirmation }),
                        ),
                      )
                    }
                  >
                    Approve physical run
                  </button>
                  <button
                    className={s.secondary}
                    disabled={busy}
                    onClick={() =>
                      void act(() =>
                        api(
                          `/pair-runs/${run.run_id}/reject`,
                          json({
                            expected_version: run.version,
                            reason: "Rejected by operator",
                          }),
                        ),
                      )
                    }
                  >
                    Reject
                  </button>
                </div>
              </div>
            )}
            <div className={s.scroll}>
              <table>
                <thead>
                  <tr>
                    <th>Step</th>
                    <th>Twin</th>
                    <th>Gate</th>
                    <th>Real</th>
                    <th>Comparison</th>
                  </tr>
                </thead>
                <tbody>
                  {run.steps.map((step) => (
                    <tr key={step.operation.operation_id}>
                      <th>
                        <small>{step.operation.operation_id}</small>
                        {label(step.operation.action)}
                      </th>
                      <SideCell side={step.sim} kind="Twin" />
                      <td data-state={step.gate ?? undefined}>
                        {step.gate ?? "—"}
                      </td>
                      <SideCell side={step.real} kind="Real" />
                      <td>
                        {step.comparisons.length
                          ? step.comparisons
                              .map((c) => `${c.field}: ${c.status}`)
                              .join(" · ")
                          : "Not compared"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </article>
        ))
      )}
      <p className={s.footnote}>
        Twin results are predictions. Only physical observations count as
        physical evidence, and fields in different units or frames are never
        compared.
      </p>
    </section>
  );
}
