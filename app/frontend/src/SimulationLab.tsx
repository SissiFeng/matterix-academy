import GpuRequestPanel from "./GpuRequestPanel";
import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  Check,
  FlaskConical,
  Play,
  RefreshCw,
  X,
} from "lucide-react";
import { api, json } from "./api";
import IsaacViewport from "./IsaacViewport";
import MixingSchematic from "./MixingSchematic";
import {
  terminalRuns,
  type MixingPlan,
  type SimulationRun,
  type SimulationSession,
  type TwinOption,
  type TwinRun,
} from "./simulationTypes";
import PageStory from "./PageStory";
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
  twins: TwinOption[];
};
const NATIVE = "native";
const origins = {
  builtin: "Built in",
  device: "Your workcell",
  instrument: "Your instrument",
};
// The engine a learner chose for an experiment survives a reload.
const remembered = (id: string) => {
  try {
    return id ? sessionStorage.getItem(`lab.mixing.engine.${id}`) : null;
  } catch {
    return null;
  }
};
const remember = (id: string, engine: string) => {
  try {
    sessionStorage.setItem(`lab.mixing.engine.${id}`, engine);
  } catch {
    // The choice then lasts only until the page reloads.
  }
};

export default function SimulationLab({
  onOpenInstruments,
}: {
  onOpenInstruments: () => void;
}) {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [session, setSession] = useState<SimulationSession | null>(null);
  const [run, setRun] = useState<SimulationRun | null>(null);
  const [twinRun, setTwinRun] = useState<TwinRun | null>(null);
  const [replay, setReplay] = useState<{ id: string; step: number } | null>(
    null,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [delayed, setDelayed] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [resolved, setResolved] = useState(false);
  const [selectedId, setSelectedId] = useState(
    () => window.location.hash.match(/^#\/sim\/([a-f0-9-]+)$/)?.[1] ?? "",
  );
  const [picked, setPicked] = useState(() => remembered(selectedId));
  const alive = useRef(true);
  const mutation = useRef(0);
  const inFlight = useRef(false);
  const launch = useRef<{ session_id: string; seed: number } | null>(null);
  // Milliseconds between status reads; only a live GPU run needs the fast rate.
  const pace = useRef(2000);
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
    let catalogAt = 0;
    // A twin run changes only when this page starts one, so it is read once.
    let twinLoaded = false;
    const poll = async () => {
      if (document.hidden) {
        timer = window.setTimeout(poll, 2000);
        return;
      }
      const epoch = mutation.current;
      try {
        if (Date.now() - catalogAt >= 10000) {
          const nextCatalog = await api<Catalog>("/simulations", {
            signal: controller.signal,
          });
          if (!active) return;
          setCatalog(nextCatalog);
          catalogAt = Date.now();
        }
        if (selectedId) {
          const [nextSession, nextRun, nextTwinRun] = await Promise.all([
            api<SimulationSession>(`/sessions/${selectedId}`, {
              signal: controller.signal,
            }),
            api<SimulationRun | null>(`/sessions/${selectedId}/remote-run`, {
              signal: controller.signal,
            }),
            twinLoaded
              ? undefined
              : api<TwinRun | null>(`/simulations/${selectedId}/twin-run`, {
                  signal: controller.signal,
                }),
          ]);
          if (!active || epoch !== mutation.current) return;
          if (nextSession.experiment.course_id !== "flex-mixing")
            throw new Error("This session is not a mixing simulation.");
          setSession(nextSession);
          if (nextTwinRun !== undefined) {
            setTwinRun(nextTwinRun);
            twinLoaded = true;
          }
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
        if (active) timer = window.setTimeout(poll, pace.current);
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
    setTwinRun(null);
    setReplay(null);
    setPicked(remembered(id));
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
  const prepareSession = async () => {
    if (session) return session;
    launch.current ??= { session_id: crypto.randomUUID(), seed: 42 };
    const prepared = await api<SimulationSession>(
      "/simulations",
      json(launch.current),
    );
    if (alive.current) {
      setSession(prepared);
      setSelectedId(prepared.id);
      window.history.replaceState({}, "", `/#/sim/${prepared.id}`);
      launch.current = null;
      remember(prepared.id, engine);
    }
    return prepared;
  };
  // A native run owns the view; otherwise the last twin used, else what can run here.
  // A remembered or last-used twin may since have been removed.
  const offered = (key: string | null | undefined) =>
    key && (key === NATIVE || catalog?.twins.some((item) => item.key === key))
      ? key
      : null;
  const engine =
    run && !run.cleanup?.reset_verified
      ? NATIVE
      : (offered(picked) ??
        (run
          ? NATIVE
          : (offered(twinRun?.twin.key) ??
            (catalog?.enabled ? NATIVE : (catalog?.twins[0]?.key ?? NATIVE)))));
  const twin = catalog?.twins.find((item) => item.key === engine);
  const frames = twinRun?.frames.length ?? 0;
  const replaying =
    !!replay && replay.id === twinRun?.run_id && replay.step < frames - 1;
  const shown = twinRun
    ? replay?.id === twinRun.run_id
      ? Math.min(replay.step, frames - 1)
      : frames - 1
    : 0;
  useEffect(() => {
    if (!replaying) return;
    const timer = window.setTimeout(
      () => setReplay((old) => old && { ...old, step: old.step + 1 }),
      700,
    );
    return () => window.clearTimeout(timer);
  }, [replaying, replay?.step]);
  const pick = (next: string) => {
    setPicked(next);
    setReplay(null);
    setError("");
    if (selectedId) remember(selectedId, next);
  };
  const startTwin = async () => {
    if (
      inFlight.current ||
      !twin ||
      !resolved ||
      (selectedId && session?.id !== selectedId)
    )
      return;
    inFlight.current = true;
    mutation.current += 1;
    setBusy(true);
    setError("");
    try {
      const current = await prepareSession();
      if (!alive.current) return;
      const key = `lab.mixing.twin.${current.id}`;
      const saved = JSON.parse(sessionStorage.getItem(key) ?? "null");
      const request =
        saved?.twin === twin.key && saved.expected_version === current.version
          ? saved
          : {
              run_id: crypto.randomUUID(),
              expected_version: current.version,
              twin: twin.key,
            };
      sessionStorage.setItem(key, JSON.stringify(request));
      const result = await api<TwinRun>(
        `/simulations/${current.id}/twin-run`,
        json(request),
      );
      sessionStorage.removeItem(key);
      if (!alive.current) return;
      setTwinRun(result);
      setReplay(
        window.matchMedia("(prefers-reduced-motion: reduce)").matches
          ? null
          : { id: result.run_id, step: 0 },
      );
    } catch (e) {
      if (alive.current) setError((e as Error).message);
    } finally {
      inFlight.current = false;
      if (alive.current) setBusy(false);
    }
  };
  const requestGpu = async () => {
    if (inFlight.current || !resolved || selectedId || delayed) return;
    inFlight.current = true;
    mutation.current += 1;
    setBusy(true);
    setError("");
    try {
      const prepared = await prepareSession();
      if (!alive.current) return;
      // Capacity demand is separate from /runs, including on a first visit.
      await api(
        `/sessions/${prepared.id}/gpu-request`,
        json({
          request_id: prepared.id,
          expected_version: prepared.version,
        }),
      );
    } catch (cause) {
      if (alive.current)
        setError(
          cause instanceof Error
            ? cause.message
            : "The GPU request could not be confirmed. Check GPU connection to recover it.",
        );
    } finally {
      inFlight.current = false;
      if (alive.current) {
        setBusy(false);
        setRefresh((n) => n + 1);
      }
    }
  };
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
      const current = await prepareSession();
      if (!alive.current) return;
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
  const native = engine === NATIVE;
  const state = native ? run?.snapshot?.native_state : undefined;
  const mixing = state?.mixing;
  // Shown only for the twin that produced it.
  const result = !native && twinRun?.twin.key === engine ? twinRun : null;
  const frame = result?.frames[shown];
  const observed = native ? mixing : frame;
  const stopped = !!result?.stop && !replaying;
  const stale =
    delayed ||
    (native &&
      !!run &&
      !terminalRuns.has(run.status) &&
      run.stale_seconds > 10);
  const locked = !!run && !run.cleanup?.reset_verified;
  const total = plan?.actions.length ?? 5;
  const confirmed = native ? (run?.completed_steps ?? 0) : result ? shown : 0;
  const tone = stale
    ? "stale"
    : native
      ? run?.status === "failed" || run?.status === "outcome_unknown"
        ? "fault"
        : run && !terminalRuns.has(run.status)
          ? "live"
          : run?.status === "completed"
            ? "done"
            : "idle"
      : replaying
        ? "live"
        : stopped
          ? "fault"
          : result
            ? "done"
            : "idle";
  const hasEnded = !!run && terminalRuns.has(run.status);
  pace.current = run && !hasEnded ? 2000 : native ? 5000 : 15000;
  const a1 = native
    ? state?.well_volumes_ul.A1
    : frame?.mixture_components_ul.reduce((a, b) => a + b, 0);
  return (
    <div className={s.page}>
      <button className={s.secondary} onClick={onOpenInstruments}>
        Design a multi-device workflow <ArrowRight size={16} />
      </button>
      <header className={s.heading}>
        <div>
          <h1>Four sources. One mixture.</h1>
          <p>Opentrons Flex · 40 µL mixture</p>
          <PageStory page="sim" />
        </div>
        <div className={s.launch}>
          <fieldset className={s.engines} disabled={busy || locked}>
            <legend>Run on</legend>
            {catalog?.twins.map((item) => (
              <label key={item.key}>
                <input
                  type="radio"
                  name="engine"
                  checked={engine === item.key}
                  onChange={() => pick(item.key)}
                />
                <span>
                  {item.name}
                  <small>{origins[item.kind]} · synthetic</small>
                </span>
              </label>
            ))}
            <label>
              <input
                type="radio"
                name="engine"
                checked={native}
                onChange={() => pick(NATIVE)}
              />
              <span>
                Digital twin on GPU
                <small>
                  {catalog?.enabled
                    ? "Isaac · live view"
                    : "Awaiting qualification"}
                </small>
              </span>
            </label>
          </fieldset>
          {native && hasEnded && run.cleanup?.reset_verified ? (
            <button className={s.primary} onClick={() => select("")}>
              <RefreshCw size={16} /> New experiment
            </button>
          ) : (
            <button
              className={s.primary}
              disabled={
                busy ||
                locked ||
                replaying ||
                !resolved ||
                (native ? !catalog?.enabled : !twin)
              }
              onClick={native ? start : startTwin}
            >
              <Play size={16} />
              {busy
                ? "Submitting…"
                : locked
                  ? (labels[run?.status ?? ""] ?? "Run in progress")
                  : "Run mixing experiment"}
            </button>
          )}
          {native && !session && (
            <button
              className={s.primary}
              disabled={busy || !resolved || !!selectedId || delayed}
              onClick={() => void requestGpu()}
            >
              {busy ? "Requesting GPU…" : "Request GPU"}
            </button>
          )}
          <small>seed 42 · 4 fresh tips</small>
        </div>
      </header>
      {native && session && (
        <GpuRequestPanel key={session.id} session={session} />
      )}
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
      <div className={s.workspace}>
        {native ? (
          <IsaacViewport run={run} />
        ) : (
          <MixingSchematic
            name={twin?.name ?? result?.twin.name ?? "Teaching twin"}
            plan={plan}
            frame={frame}
            active={replaying ? shown : null}
          />
        )}
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
            aria-label={native ? "Confirmed native steps" : "Completed steps"}
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
                : native
                  ? run
                    ? (labels[run.status] ?? run.status)
                    : "Ready to prepare"
                  : replaying
                    ? "Running"
                    : stopped
                      ? `Stopped at step ${result?.stop?.step}`
                      : result
                        ? "Completed"
                        : "Ready to run"}
            </span>
            {native && run && !terminalRuns.has(run.status) && (
              <span className={s.freshness}>
                {run.stale_seconds <= 2
                  ? "updated just now"
                  : `updated ${run.stale_seconds}s ago`}
              </span>
            )}
          </div>
          <ol className={s.steps}>
            {plan?.actions.map((step, index) => {
              const status = native
                ? (run?.snapshot?.steps[index]?.status ?? "pending")
                : !result || index > shown
                  ? "pending"
                  : index < shown
                    ? "completed"
                    : replaying
                      ? "running"
                      : stopped
                        ? "stopped"
                        : "pending";
              const current =
                tone === "live" &&
                status !== "completed" &&
                (native
                  ? (run?.snapshot?.steps ?? []).findIndex(
                      (item) => item.status !== "completed",
                    )
                  : shown) === index;
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
          {native ? (
            <div className={s.currentAction}>
              <span>CURRENT NATIVE ACTION</span>
              <p>
                {mixing?.native_action ?? "Waiting for a native observation"}
              </p>
              {mixing && (
                <small>
                  {mixing.native_action_index} / {mixing.native_action_count}{" "}
                  actions
                </small>
              )}
            </div>
          ) : (
            stopped && (
              <div className={s.currentAction} data-stopped role="alert">
                <span>{result?.stop?.layer.toUpperCase()} LAYER</span>
                <p>{result?.stop?.message}</p>
              </div>
            )
          )}
        </aside>
      </div>
      <section className={s.observations}>
        <div className={s.sectionTitle}>
          <h2>{native ? "Native observations" : "Teaching twin state"}</h2>
          <span>
            {native
              ? state
                ? `Revision ${state.revision} · tick ${state.simulation_tick}`
                : "No native state received"
              : result
                ? `${result.twin.name} · synthetic`
                : "Not run yet"}
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
            <strong>{amount(a1)}</strong>
            <small>Target: 40 µL</small>
          </div>
          <div>
            <span>Liquid in the tool</span>
            <strong>
              {amount(native ? state?.pipette_volume_ul : undefined)}
            </strong>
            <small>
              {mixing
                ? (mixing.active_tip?.replace("Tips__", "Tip ") ??
                  "No tip attached")
                : native
                  ? "Not observed"
                  : "Not modelled by this twin"}
            </small>
          </div>
          <div>
            <span>Tips used / discarded</span>
            <strong>
              {observed
                ? `${observed.tips_used.length} / ${observed.tips_discarded.length}`
                : "—"}
            </strong>
            <small>4 fresh tips planned</small>
          </div>
          <div>
            <span>Source lid</span>
            <strong>
              {observed
                ? mixing?.lid_attached
                  ? "In gripper"
                  : observed.lid_parked
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
                <strong>{amount(observed?.source_volumes_ul[index])}</strong>
                <small>
                  {amount(observed?.mixture_components_ul[index])} in A1
                </small>
                <div className={s.volumeTrack}>
                  <i
                    style={{
                      width: observed
                        ? `${Math.min(100, (observed.source_volumes_ul[index] / 1500) * 100)}%`
                        : "0%",
                    }}
                  />
                </div>
              </div>
            );
          })}
        </div>
        <p className={s.modelNote}>
          {native
            ? "Liquid quantities and attachments are digital twin semantic observations. They do not validate fluid dynamics, grip forces or physical chemistry."
            : "Synthetic bookkeeping from a teaching twin. Not an Isaac/GPU run, a physical robot run or chemical validation."}
        </p>
      </section>
      {result && !replaying && (
        <section className={s.receipt}>
          <div>
            <strong>Run receipt</strong>
            <span>{result.run_id}</span>
            <small>
              {result.twin.name} · revision {result.twin.revision} · synthetic
            </small>
          </div>
          <ul className={s.checks}>
            {result.checks.map((check) => (
              <li key={check.label} data-passed={check.passed}>
                {check.passed ? <Check size={15} /> : <X size={15} />}
                {check.label}
              </li>
            ))}
          </ul>
        </section>
      )}
      {native && run && (
        <section className={s.receipt}>
          <div>
            <strong>Run receipt</strong>
            <span>{run.run_id}</span>
            <small>
              {run.cleanup?.never_started
                ? "Not dispatched · reservation released"
                : run.cleanup?.reset_verified
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
              <dt>Digital twin revision</dt>
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
