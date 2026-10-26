import { useEffect, useRef, useState } from "react";
import { ArrowRight, Check, FlaskConical, Play, RefreshCw } from "lucide-react";
import { api, json } from "./api";
import IsaacViewport from "./IsaacViewport";
import {
  terminalRuns,
  type MixingPlan,
  type SimulationRun,
  type SimulationSession,
} from "./simulationTypes";
import s from "./SimulationLab.module.css";

const amount = (value: number | null | undefined) =>
  value == null ? "—" : `${Number(value.toFixed(2))} µL`;
const labels: Record<string, string> = {
  queued: "Waiting for the lab",
  claimed: "Lab reserved",
  starting: "Preparing Isaac",
  running: "Running",
  completed: "Completed",
  failed: "Failed",
  outcome_unknown: "Outcome needs review",
  cancelled: "Cancelled",
};

type Catalog = {
  commissioning?: boolean;
  commissioning_expires?: number | null;
  enabled: boolean;
  recipe: MixingPlan;
  sessions: SimulationSession[];
};

export default function SimulationLab() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [session, setSession] = useState<SimulationSession | null>(null);
  const [run, setRun] = useState<SimulationRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [delayed, setDelayed] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [resolved, setResolved] = useState(false);
  const [selectedId, setSelectedId] = useState(
    () => window.location.hash.match(/^#\/sim\/([a-f0-9-]+)$/)?.[1] ?? "",
  );
  const alive = useRef(true);
  const mutation = useRef(0);
  const inFlight = useRef(false);
  const launch = useRef<{ session_id: string; seed: number } | null>(null);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    const controller = new AbortController();
    setResolved(false);
    const poll = async () => {
      const epoch = mutation.current;
      try {
        const nextCatalog = await api<Catalog>("/simulations", {
          signal: controller.signal,
        });
        if (!active) return;
        setCatalog(nextCatalog);
        if (selectedId) {
          const [nextSession, nextRun] = await Promise.all([
            api<SimulationSession>(`/sessions/${selectedId}`, {
              signal: controller.signal,
            }),
            api<SimulationRun | null>(`/sessions/${selectedId}/remote-run`, {
              signal: controller.signal,
            }),
          ]);
          if (!active || epoch !== mutation.current) return;
          if (nextSession.experiment.course_id !== "flex-mixing")
            throw new Error("This session is not a mixing simulation.");
          setSession(nextSession);
          setRun((old) =>
            old &&
            nextRun?.run_id === old.run_id &&
            nextRun.version < old.version
              ? old
              : nextRun,
          );
        }
        setResolved(true);
        setDelayed(false);
      } catch (e) {
        if (active) {
          setDelayed(true);
          if (!catalog) setError((e as Error).message);
        }
      } finally {
        if (active) timer = window.setTimeout(poll, 2000);
      }
    };
    void poll();
    return () => {
      active = false;
      controller.abort();
      window.clearTimeout(timer);
    };
    // The current catalog is deliberately not a polling dependency.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, refresh]);
  const select = (id: string) => {
    mutation.current += 1;
    setResolved(false);
    setSession(null);
    setRun(null);
    setError("");
    setSelectedId(id);
    window.history.replaceState({}, "", `/#/sim${id ? `/${id}` : ""}`);
  };
  useEffect(() => {
    const changed = () => {
      const id =
        window.location.hash.match(/^#\/sim\/([a-f0-9-]+)$/)?.[1] ?? "";
      if (id !== selectedId) select(id);
    };
    window.addEventListener("hashchange", changed);
    // This page loads lazily; a hash change that landed before the listener
    // was attached must still select the linked experiment.
    if (window.location.hash.startsWith("#/sim")) changed();
    return () => window.removeEventListener("hashchange", changed);
  }, [selectedId]);
  const start = async () => {
    if (
      inFlight.current ||
      !catalog?.enabled ||
      !resolved ||
      (selectedId && session?.id !== selectedId)
    )
      return;
    inFlight.current = true;
    mutation.current += 1;
    setBusy(true);
    setError("");
    try {
      let current = session;
      if (!current) {
        launch.current ??= { session_id: crypto.randomUUID(), seed: 42 };
        current = await api<SimulationSession>(
          "/simulations",
          json(launch.current),
        );
        if (!alive.current) return;
        setSession(current);
        setSelectedId(current.id);
        window.history.replaceState({}, "", `/#/sim/${current.id}`);
        launch.current = null;
      }
      const key = `lab.mixing.submit.${current.id}`;
      const request = JSON.parse(sessionStorage.getItem(key) ?? "null") ?? {
        run_id: crypto.randomUUID(),
        session_id: current.id,
        expected_version: current.version,
      };
      sessionStorage.setItem(key, JSON.stringify(request));
      const result = await api<SimulationRun>("/runs", json(request));
      if (!alive.current) return;
      setRun(result);
      sessionStorage.removeItem(key);
      setRefresh((n) => n + 1);
    } catch (e) {
      if (alive.current) setError((e as Error).message);
    } finally {
      inFlight.current = false;
      if (alive.current) setBusy(false);
    }
  };
  const plan = session?.experiment ?? catalog?.recipe;
  const state = run?.snapshot?.native_state;
  const mixing = state?.mixing;
  const stale =
    delayed ||
    (!!run && !terminalRuns.has(run.status) && run.stale_seconds > 10);
  const locked = !!run && !run.cleanup?.reset_verified;
  const total = plan?.actions.length ?? 5;
  const confirmed = run?.completed_steps ?? 0;
  const tone = stale
    ? "stale"
    : run?.status === "failed" || run?.status === "outcome_unknown"
      ? "fault"
      : run && !terminalRuns.has(run.status)
        ? "live"
        : run?.status === "completed"
          ? "done"
          : "idle";
  const hasEnded = !!run && terminalRuns.has(run.status);
  return (
    <div className={s.page}>
      <header className={s.heading}>
        <div>
          <h1>Four sources. One mixture.</h1>
          <p>Opentrons Flex · 40 µL mixture</p>
        </div>
        <div className={s.launch}>
          {hasEnded && run.cleanup?.reset_verified ? (
            <button className={s.primary} onClick={() => select("")}>
              <RefreshCw size={16} /> New experiment
            </button>
          ) : (
            <button
              className={s.primary}
              disabled={busy || locked || !catalog?.enabled || !resolved}
              onClick={start}
            >
              <Play size={16} />
              {busy
                ? "Submitting…"
                : locked
                  ? (labels[run?.status ?? ""] ?? "Run in progress")
                  : "Run mixing experiment"}
            </button>
          )}
          <small>
            {catalog?.enabled
              ? "1 simulation · seed 42 · 4 fresh tips"
              : "Native lab awaiting qualification"}
          </small>
        </div>
      </header>
      {catalog?.commissioning && (
        <p className={s.notice}>
          Operator commissioning window · fixed seed 42 · at most two runs. This
          host is not yet qualified for general learner access.
        </p>
      )}
      {error && (
        <div role="alert" className={s.alert}>
          {error}
          <button
            onClick={() => {
              setError("");
              setRefresh((n) => n + 1);
            }}
          >
            Refresh
          </button>
        </div>
      )}
      {!catalog?.enabled && (
        <p className={s.notice}>
          The Ubuntu runtime is not yet qualified for this deployment. Starting
          native runs is disabled; no simulated progress or substitute video is
          shown here.
        </p>
      )}
      <div className={s.workspace}>
        <IsaacViewport run={run} />
        <aside className={s.progress}>
          <div className={s.sectionTitle}>
            <h2>Experiment progress</h2>
            <span>
              {confirmed} / {total}
            </span>
          </div>
          <div
            className={s.progressTrack}
            role="progressbar"
            aria-label="Confirmed native steps"
            aria-valuemin={0}
            aria-valuemax={total}
            aria-valuenow={confirmed}
          >
            <span
              data-tone={tone}
              style={{ width: `${(100 * confirmed) / Math.max(total, 1)}%` }}
            />
          </div>
          <div className={s.statusRow} data-tone={tone}>
            <i className={s.statusDot} />
            <span>
              {stale
                ? "Status delayed"
                : run
                  ? (labels[run.status] ?? run.status)
                  : "Ready to prepare"}
            </span>
            {run && !terminalRuns.has(run.status) && (
              <span className={s.freshness}>
                {run.stale_seconds <= 2
                  ? "updated just now"
                  : `updated ${run.stale_seconds}s ago`}
              </span>
            )}
          </div>
          <ol className={s.steps}>
            {plan?.actions.map((step, index) => {
              const status = run?.snapshot?.steps[index]?.status ?? "pending";
              const current =
                tone === "live" &&
                status !== "completed" &&
                (run?.snapshot?.steps ?? []).findIndex(
                  (item) => item.status !== "completed",
                ) === index;
              return (
                <li
                  key={index}
                  data-status={status}
                  data-current={current || undefined}
                  aria-current={current ? "step" : undefined}
                >
                  <span className={s.stepNumber}>
                    {status === "completed" ? <Check size={15} /> : index + 1}
                  </span>
                  <div>
                    <strong>
                      {step.kind === "uncover"
                        ? "Uncover the source vials"
                        : `Vial ${(step.source_index ?? 0) + 1} → well A1`}
                    </strong>
                    <small>
                      {step.kind === "uncover"
                        ? "Gripper · move the lid from C1 to D4"
                        : `10 µL · fresh tip ${step.tip_id?.replace("Tips__", "")}`}
                    </small>
                    <span className={s.stepStatus}>{status}</span>
                  </div>
                </li>
              );
            })}
          </ol>
          <div className={s.currentAction}>
            <span>CURRENT NATIVE ACTION</span>
            <p>{mixing?.native_action ?? "Waiting for a native observation"}</p>
            {mixing && (
              <small>
                {mixing.native_action_index} / {mixing.native_action_count}{" "}
                actions
              </small>
            )}
          </div>
        </aside>
      </div>
      <section className={s.observations}>
        <div className={s.sectionTitle}>
          <h2>Native observations</h2>
          <span>
            {state
              ? `Revision ${state.revision} · tick ${state.simulation_tick}`
              : "No native state received"}
          </span>
        </div>
        {stale && (
          <p role="status" className={s.notice}>
            Last received state is shown. Connection loss does not confirm that
            motion stopped.
          </p>
        )}
        <div className={s.metrics}>
          <div>
            <span>Mixture in A1</span>
            <strong>{amount(state?.well_volumes_ul.A1)}</strong>
            <small>Target: 40 µL</small>
          </div>
          <div>
            <span>Liquid in the tool</span>
            <strong>{amount(state?.pipette_volume_ul)}</strong>
            <small>
              {mixing
                ? (mixing.active_tip?.replace("Tips__", "Tip ") ??
                  "No tip attached")
                : "Not observed"}
            </small>
          </div>
          <div>
            <span>Tips used / discarded</span>
            <strong>
              {mixing
                ? `${mixing.tips_used.length} / ${mixing.tips_discarded.length}`
                : "—"}
            </strong>
            <small>4 fresh tips planned</small>
          </div>
          <div>
            <span>Source lid</span>
            <strong>
              {mixing
                ? mixing.lid_attached
                  ? "In gripper"
                  : mixing.lid_parked
                    ? "Parked on D4"
                    : "Over vials"
                : "—"}
            </strong>
            <small>C1 source rack</small>
          </div>
        </div>
        <div className={s.sourceGrid}>
          {Array.from({ length: 8 }, (_, index) => {
            const selected = plan?.actions.some(
              (step) => step.source_index === index,
            );
            return (
              <div className={s.vial} key={index} data-selected={selected}>
                <span>
                  VIAL {index + 1}
                  {selected && <FlaskConical size={13} />}
                </span>
                <strong>{amount(mixing?.source_volumes_ul[index])}</strong>
                <small>
                  {amount(mixing?.mixture_components_ul[index])} in A1
                </small>
                <div className={s.volumeTrack}>
                  <i
                    style={{
                      width: mixing
                        ? `${Math.min(100, (mixing.source_volumes_ul[index] / 1500) * 100)}%`
                        : "0%",
                    }}
                  />
                </div>
              </div>
            );
          })}
        </div>
        <p className={s.modelNote}>
          Liquid quantities and attachments are Matterix semantic observations.
          They do not validate fluid dynamics, grip forces or physical
          chemistry.
        </p>
      </section>
      {run && (
        <section className={s.receipt}>
          <div>
            <strong>Run receipt</strong>
            <span>{run.run_id}</span>
            <small>
              {run.cleanup?.reset_verified
                ? "Reset verified · lab released"
                : hasEnded
                  ? "Lab remains reserved until reset is verified"
                  : "Reserved for this experiment"}
            </small>
          </div>
          <details>
            <summary>Runtime and state provenance</summary>
            <dl>
              <dt>Native session</dt>
              <dd>{run.snapshot?.session_id ?? "Not bound yet"}</dd>
              <dt>Plan SHA-256</dt>
              <dd>{run.plan_hash}</dd>
              <dt>Matterix revision</dt>
              <dd>{run.snapshot?.engine_version ?? "Not observed"}</dd>
              <dt>Assets revision</dt>
              <dd>{run.snapshot?.asset_version ?? "Not observed"}</dd>
              <dt>Observed at</dt>
              <dd>{state?.observed_at ?? "Not observed"}</dd>
            </dl>
          </details>
          {(run.reason || run.snapshot?.error) && (
            <p role="alert">{run.reason || run.snapshot?.error}</p>
          )}
        </section>
      )}
      {!!catalog?.sessions.length && (
        <section className={s.history}>
          <h2>Your mixing experiments</h2>
          {catalog.sessions.slice(0, 8).map((item) => (
            <button
              key={item.id}
              disabled={busy || item.id === selectedId}
              onClick={() => select(item.id)}
            >
              <span>
                {item.experiment.title}
                <small>
                  {item.id.slice(0, 8)} · seed {item.experiment.seed}
                </small>
              </span>
              <ArrowRight size={17} />
            </button>
          ))}
        </section>
      )}
    </div>
  );
}
