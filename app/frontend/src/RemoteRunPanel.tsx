import { useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Play, RefreshCw } from "lucide-react";
import { api, ApiError, json } from "./api";
import type { Session } from "./types";
import s from "./RemoteRunPanel.module.css";

type RemoteRun = {
  run_id: string;
  session_id: string;
  version: number;
  status: string;
  evidence: "pending" | "native";
  completed_steps: number;
  total_steps: number;
  stale_seconds: number;
  supported_controls: string[];
  reason?: string;
  control: { action: string; acknowledged: boolean } | null;
  cleanup: { reset_verified: boolean } | null;
  snapshot: {
    observed_at: string;
    engine_version: string;
    asset_version: string;
    steps: { index: number; status: string }[];
    native_state: {
      pipette_volume_ul: number | null;
      tip_attached: boolean | null;
      well_volumes_ul: Record<string, number | null>;
    } | null;
  } | null;
};
const terminal = new Set([
  "completed",
  "failed",
  "cancelled",
  "outcome_unknown",
]);
const labels: Record<string, string> = {
  queued: "Waiting for the lab",
  claimed: "Lab reserved",
  starting: "Starting simulation",
  running: "Running",
  pause_requested: "Pause requested",
  paused: "Paused",
  resume_requested: "Resume requested",
  cancel_requested: "Cancel requested",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
  outcome_unknown: "Outcome unknown",
};
const volume = (value: number | null | undefined) =>
  value == null ? "Not observed" : `${value} µL`;

export default function RemoteRunPanel({
  session,
  dirty,
  onChange,
}: {
  session: Session;
  dirty: boolean;
  onChange: (next: Session) => void;
}) {
  const [run, setRun] = useState<RemoteRun | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const alive = useRef(false);
  const requestInFlight = useRef(false);
  const latestVersion = useRef(0);
  const latestRun = useRef("");
  const mutationEpoch = useRef(0);
  const key = `academy.remote-request.${session.id}`;

  useEffect(() => {
    alive.current = true;
    let active = true;
    let timer: number | undefined;
    const controller = new AbortController();
    const poll = async () => {
      const epoch = mutationEpoch.current;
      let delay = 2000;
      try {
        const [status, next] = await Promise.all([
          api<{ enabled: boolean }>("/runs/status", {
            signal: controller.signal,
          }),
          api<RemoteRun | null>(`/sessions/${session.id}/remote-run`, {
            signal: controller.signal,
          }),
        ]);
        if (!active) return;
        setEnabled(status.enabled);
        if (
          epoch === mutationEpoch.current &&
          next &&
          (next.run_id !== latestRun.current ||
            next.version >= latestVersion.current)
        ) {
          latestRun.current = next.run_id;
          latestVersion.current = next.version;
          setRun(next);
        }
        setReconnecting(false);
        setLoaded(true);
        if (!next || terminal.has(next.status)) delay = 10000;
      } catch {
        if (!active) return;
        setReconnecting(true);
        delay = 5000;
      }
      if (active) timer = window.setTimeout(poll, delay);
    };
    void poll();
    return () => {
      active = false;
      alive.current = false;
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [session.id, refresh]);

  const update = (next: RemoteRun) => {
    if (
      !alive.current ||
      next.session_id !== session.id ||
      (next.run_id === latestRun.current &&
        next.version < latestVersion.current)
    )
      return;
    latestVersion.current = next.version;
    latestRun.current = next.run_id;
    setRun(next);
  };
  const submit = async () => {
    if (requestInFlight.current) return;
    requestInFlight.current = true;
    mutationEpoch.current += 1;
    setBusy(true);
    setError("");
    try {
      const cached = sessionStorage.getItem(key);
      const request = cached
        ? JSON.parse(cached)
        : {
            run_id: crypto.randomUUID(),
            session_id: session.id,
            expected_version: session.version,
          };
      // Persist before transmission, so a refresh/lost response keeps the same ID.
      sessionStorage.setItem(key, JSON.stringify(request));
      const next = await api<RemoteRun>("/runs", json(request));
      if (!alive.current) return;
      update(next);
      sessionStorage.removeItem(key);
      const current = await api<Session>(`/sessions/${session.id}`);
      if (alive.current) onChange(current);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && alive.current) {
        const cached = sessionStorage.getItem(key);
        if (cached) {
          const pending = JSON.parse(cached);
          try {
            const existing = await api<RemoteRun>(`/runs/${pending.run_id}`);
            update(existing);
            sessionStorage.removeItem(key);
          } catch (lookup) {
            if (lookup instanceof ApiError && lookup.status === 404) {
              try {
                const current = await api<Session>(`/sessions/${session.id}`);
                if (
                  alive.current &&
                  current.version > pending.expected_version
                ) {
                  // The original CAS can no longer succeed, including a delayed request.
                  sessionStorage.removeItem(key);
                  onChange(current);
                }
              } catch {
                // Keep the request ID until the server can resolve its outcome.
              }
            }
          }
        }
      }
      if (alive.current)
        setError(
          e instanceof ApiError && e.status === 409
            ? "The saved experiment changed. Check its current state before submitting again."
            : "The submission could not be confirmed. Check connection to recover this run; a retry keeps the same request ID.",
        );
    } finally {
      requestInFlight.current = false;
      if (alive.current) setBusy(false);
    }
  };
  const control = async (action: string) => {
    if (!run || requestInFlight.current) return;
    requestInFlight.current = true;
    mutationEpoch.current += 1;
    setBusy(true);
    setError("");
    try {
      update(
        await api<RemoteRun>(
          `/runs/${run.run_id}/control`,
          json({
            command_id: crypto.randomUUID(),
            expected_version: run.version,
            action,
          }),
        ),
      );
      const current = await api<Session>(`/sessions/${session.id}`);
      if (alive.current) onChange(current);
    } catch (e) {
      if (alive.current)
        setError(
          e instanceof Error
            ? e.message
            : "Control request could not be confirmed.",
        );
    } finally {
      requestInFlight.current = false;
      if (alive.current) setBusy(false);
    }
  };
  const locked = !!run && !run.cleanup?.reset_verified;
  const state = run?.snapshot?.native_state;
  return (
    <section className={s.panel} aria-label="Remote experiment run">
      <div className={s.heading}>
        <div>
          <span className={s.eyebrow}>MATTERIX / SAVED EXPERIMENT</span>
          <h3>Follow your remote run</h3>
        </div>
        <span className={s.badge}>
          {run?.evidence === "native"
            ? "Native simulation report"
            : "Awaiting native execution"}
        </span>
      </div>
      {!enabled && (
        <p>
          Remote execution is awaiting Ubuntu qualification. Your teaching
          exercises remain available.
        </p>
      )}
      {reconnecting && (
        <p className={s.warning} role="status">
          <AlertTriangle size={16} /> Reconnecting. Showing the last confirmed
          state.
        </p>
      )}
      {error && (
        <p className={s.warning} role="alert">
          {error}
        </p>
      )}
      {run ? (
        <>
          <div className={s.summary}>
            <strong>{labels[run.status] ?? run.status}</strong>
            <span>
              {run.completed_steps} / {run.total_steps} actions confirmed
            </span>
          </div>
          <progress
            aria-label="Native confirmed progress"
            value={run.completed_steps}
            max={run.total_steps}
          />
          <p className={s.meta}>
            Run {run.run_id}
            <br />
            {run.snapshot
              ? `Observed ${new Date(run.snapshot.observed_at).toLocaleString()}`
              : "No native observation received yet."}
          </p>
          {run.stale_seconds > 10 && !terminal.has(run.status) && (
            <p className={s.warning}>
              State is at least {run.stale_seconds} seconds old. Progress is not
              estimated.
            </p>
          )}
          {run.status === "outcome_unknown" && (
            <p className={s.warning}>
              The lab could not confirm the outcome. This run will not restart
              automatically. An operator must reconcile and verify the reset.
            </p>
          )}
          {run.snapshot && (
            <dl className={s.observations}>
              <div>
                <dt>Source</dt>
                <dd>{volume(state?.well_volumes_ul.stock)}</dd>
              </div>
              <div>
                <dt>Target A1</dt>
                <dd>{volume(state?.well_volumes_ul.A1)}</dd>
              </div>
              <div>
                <dt>Liquid in tip</dt>
                <dd>{volume(state?.pipette_volume_ul)}</dd>
              </div>
              <div>
                <dt>Tip attached</dt>
                <dd>
                  {state?.tip_attached == null
                    ? "Not observed"
                    : state.tip_attached
                      ? "Yes"
                      : "No"}
                </dd>
              </div>
            </dl>
          )}
          {terminal.has(run.status) && (
            <p>
              {run.cleanup?.reset_verified ? (
                <>
                  <CheckCircle2 size={15} /> Reset verified. The lab is ready
                  for another attempt.
                </>
              ) : (
                "The session stays reserved until the lab verifies cleanup."
              )}
            </p>
          )}
          <div className={s.actions}>
            {run.status === "queued" && (
              <button
                disabled={busy || reconnecting}
                onClick={() => void control("cancel")}
              >
                Cancel queued run
              </button>
            )}
            {run.status === "running" &&
              run.supported_controls.includes("pause") && (
                <button
                  disabled={busy || reconnecting}
                  onClick={() => void control("pause")}
                >
                  Request pause
                </button>
              )}
            {run.status === "paused" &&
              run.supported_controls.includes("resume") && (
                <button
                  disabled={busy || reconnecting}
                  onClick={() => void control("resume")}
                >
                  Request resume
                </button>
              )}
          </div>
        </>
      ) : (
        <p>
          Submit the saved workflow after preparation. Confirmed progress and
          available observations from that same run will appear here.
        </p>
      )}
      <div className={s.actions}>
        <button
          className={s.primary}
          disabled={
            !loaded ||
            !enabled ||
            busy ||
            locked ||
            dirty ||
            !session.readiness?.ready ||
            session.status === "running" ||
            reconnecting
          }
          onClick={() => void submit()}
        >
          <Play size={15} /> Run saved experiment in Matterix
        </button>
        <button disabled={busy} onClick={() => setRefresh((v) => v + 1)}>
          <RefreshCw size={15} /> Check connection
        </button>
      </div>
      <small>
        Closing this page does not cancel a remote run. Native observations stay
        separate from the teaching model. Video is not connected.
      </small>
    </section>
  );
}
