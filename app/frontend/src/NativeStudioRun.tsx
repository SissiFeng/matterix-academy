import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Monitor,
  Play,
  RefreshCw,
} from "lucide-react";
import { api, ApiError, json } from "./api";
import IsaacViewport from "./IsaacViewport";
import { terminalRuns, type SimulationRun } from "./simulationTypes";
import { INSTRUMENT_NAMES } from "./studioContent";
import type { Session } from "./types";
import {
  acceptanceReport,
  readEvidence,
  saveEvidence,
  recordSubmission,
  recordRead,
  recordVideo,
  type ServerReport,
  type VideoReceipt,
} from "./commissioningEvidence";
import s from "./NativeStudioRun.module.css";

type Preflight = {
  session_id: string;
  session_version: number;
  plan_hash: string;
  instrument: "flex" | "ot2";
  scene: string;
  enabled: boolean;
  commissioning?: boolean;
  ready: boolean;
  issues: { code: string; message: string; step?: number | null }[];
  message: string;
};
type NativeRun = SimulationRun & {
  evidence: "pending" | "native";
  scene?: string;
  instrument?: "flex" | "ot2";
  supported_controls: string[];
  control: { action: string; acknowledged: boolean } | null;
};
type Submission = {
  run_id: string;
  session_id: string;
  expected_version: number;
};
const labels: Record<string, string> = {
  queued: "Waiting for a qualified worker",
  claimed: "Worker reserved",
  starting: "Preparing Isaac",
  running: "Running in Matterix",
  pause_requested: "Pause requested",
  paused: "Paused",
  resume_requested: "Resume requested",
  cancel_requested: "Cancellation requested",
  completed: "Native sequence completed",
  failed: "Native run failed",
  cancelled: "Native run cancelled",
  outcome_unknown: "Native outcome needs review",
};
const amount = (value: number | null | undefined) =>
  value == null ? "Not observed" : `${Number(value.toFixed(2))} µL`;
const requestKey = (id: string) => `academy.studio-native.${id}`;
const documentId = crypto.randomUUID();
const reloadedDocument = () =>
  (
    performance.getEntriesByType("navigation")[0] as
      PerformanceNavigationTiming | undefined
  )?.type === "reload";
export function hasPendingNativeSubmission(id: string): boolean {
  try {
    return sessionStorage.getItem(requestKey(id)) !== null;
  } catch {
    return true;
  }
}
function readSubmission(id: string): Submission | null {
  const raw = sessionStorage.getItem(requestKey(id));
  if (!raw) return null;
  const parsed = JSON.parse(raw) as Submission;
  if (
    parsed.session_id !== id ||
    typeof parsed.run_id !== "string" ||
    !/^[a-f0-9-]{36}$/.test(parsed.run_id) ||
    !Number.isSafeInteger(parsed.expected_version) ||
    parsed.expected_version < 1
  )
    throw new Error(
      "Saved submission details could not be read. Reload this workflow before continuing.",
    );
  return parsed;
}

/** A saved plan is submitted once. An uncertain mutation is recovered by reads. */
export default function NativeStudioRun({
  session,
  dirty,
  teachingBusy,
  onChange,
  onLockChange,
}: {
  session: Session;
  dirty: boolean;
  teachingBusy: boolean;
  onChange: (next: Session) => void;
  onLockChange: (locked: boolean) => void;
}) {
  const [cachedAtMount] = useState(() => {
    try {
      return { request: readSubmission(session.id), unreadable: false };
    } catch {
      return { request: null, unreadable: true };
    }
  });
  const [preflight, setPreflight] = useState<Preflight | null>(null);
  const [run, setRun] = useState<NativeRun | null>(null);
  const [pending, setPending] = useState<Submission | null>(
    cachedAtMount.request,
  );
  const [unreadable, setUnreadable] = useState(cachedAtMount.unreadable);
  const [loaded, setLoaded] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [pollingError, setPollingError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [evidenceError, setEvidenceError] = useState("");
  const [exporting, setExporting] = useState(false);
  const commissioningReport = useRef<ServerReport | null>(null);
  const current = useRef({
    session,
    dirty,
    teachingBusy,
    onChange,
    onLockChange,
  });
  current.current = { session, dirty, teachingBusy, onChange, onLockChange };
  const alive = useRef(true);
  const mutation = useRef(0);
  const inFlight = useRef(false);
  const acceptedRun = useRef<NativeRun | null>(null);
  const pendingRequest = useRef<Submission | null>(cachedAtMount.request);
  const id = session.id;

  const observeVideo = (receipt: VideoReceipt) => {
    const report = commissioningReport.current;
    if (!report || receipt.session_id !== current.current.session.id) return;
    try {
      saveEvidence(
        sessionStorage,
        recordVideo(readEvidence(sessionStorage, report), receipt, documentId),
      );
    } catch {
      setEvidenceError(
        "Acceptance evidence could not be saved. The native run is unchanged.",
      );
    }
  };
  const downloadEvidence = async () => {
    setExporting(true);
    setEvidenceError("");
    try {
      const report = await api<ServerReport>("/commissioning/report");
      const result = acceptanceReport(
        readEvidence(sessionStorage, report),
        report,
      );
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(result, null, 2) + "\n"], {
          type: "application/json",
        }),
      );
      const link = document.createElement("a");
      link.href = url;
      link.download = `studio-acceptance-${report.grant_id}.json`;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      if (result.status !== "completed")
        setEvidenceError(
          "Downloaded incomplete evidence. " + result.issues.join(" "),
        );
    } catch {
      setEvidenceError(
        "Acceptance evidence could not be downloaded. Check connection and try again.",
      );
    } finally {
      setExporting(false);
    }
  };

  const acceptRun = (next: NativeRun | null) => {
    if (!next) return;
    const previous = acceptedRun.current;
    if (next.session_id !== current.current.session.id)
      throw new Error("The native run did not match this saved workflow.");
    if (previous?.run_id === next.run_id && previous.version > next.version)
      return;
    acceptedRun.current = next;
    setRun(next);
  };
  const clearSubmission = () => {
    sessionStorage.removeItem(requestKey(id));
    pendingRequest.current = null;
    setPending(null);
    setError("");
  };
  const acceptSession = (next: Session) => {
    const latest = current.current;
    if (
      alive.current &&
      !latest.dirty &&
      next.id === latest.session.id &&
      next.version > latest.session.version
    )
      latest.onChange(next);
  };

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    const locked =
      busy ||
      !!pending ||
      unreadable ||
      !!session.remote_active_run ||
      (!!run && !run.cleanup?.reset_verified);
    current.current.onLockChange(locked);
  }, [busy, pending, unreadable, run, session.remote_active_run]);

  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    const controller = new AbortController();
    setLoaded(false);
    const poll = async () => {
      const epoch = mutation.current;
      try {
        let saved: Submission | null;
        try {
          saved = readSubmission(id);
        } catch (cause) {
          setUnreadable(true);
          throw cause;
        }
        if (!active) return;
        pendingRequest.current = saved;
        setPending(saved);
        setUnreadable(false);
        const [compatibility, linkedRun, freshSession] = await Promise.all([
          api<Preflight>(`/sessions/${id}/native-preflight`, {
            signal: controller.signal,
          }),
          api<NativeRun | null>(`/sessions/${id}/remote-run`, {
            signal: controller.signal,
          }),
          api<Session>(`/sessions/${id}`, { signal: controller.signal }),
        ]);
        if (!active || epoch !== mutation.current) return;
        if (compatibility.session_id !== id || freshSession.id !== id)
          throw new Error(
            "The compatibility check did not match this saved workflow.",
          );
        setPreflight(compatibility);
        acceptRun(linkedRun);
        if (compatibility.commissioning) {
          try {
            const report =
              commissioningReport.current ??
              (await api<ServerReport>("/commissioning/report", {
                signal: controller.signal,
              }));
            if (!active || epoch !== mutation.current) return;
            commissioningReport.current = report;
            let receipts = readEvidence(sessionStorage, report);
            if (linkedRun)
              receipts = recordRead(
                receipts,
                linkedRun,
                documentId,
                reloadedDocument(),
                Date.now(),
              );
            saveEvidence(sessionStorage, receipts);
          } catch {
            if (active)
              setEvidenceError(
                "Acceptance recording is unavailable. Check connection before submitting.",
              );
          }
        }
        if (saved) {
          if (linkedRun?.run_id === saved.run_id) {
            clearSubmission();
          } else {
            try {
              const recovered = await api<NativeRun>(`/runs/${saved.run_id}`, {
                signal: controller.signal,
              });
              if (!active || epoch !== mutation.current) return;
              acceptRun(recovered);
              clearSubmission();
            } catch (lookup) {
              if (!(lookup instanceof ApiError && lookup.status === 404))
                throw lookup;
              // A newer revision is a CAS barrier: the old request can no longer commit.
              // A 404 by itself never authorizes another submission.
              if (freshSession.version > saved.expected_version)
                clearSubmission();
            }
          }
        }
        if (!active || epoch !== mutation.current) return;
        acceptSession(freshSession);
        setLoaded(true);
        setReconnecting(false);
        setPollingError("");
      } catch (cause) {
        if (!active || epoch !== mutation.current) return;
        setReconnecting(true);
        if (
          cause instanceof SyntaxError ||
          (cause instanceof Error &&
            cause.message.startsWith("Saved submission"))
        )
          setUnreadable(true);
        setPollingError(
          cause instanceof Error
            ? cause.message
            : "The saved workflow could not be checked.",
        );
      } finally {
        if (active)
          timer = window.setTimeout(
            poll,
            (acceptedRun.current &&
              !terminalRuns.has(acceptedRun.current.status)) ||
              pendingRequest.current
              ? 2000
              : 8000,
          );
      }
    };
    void poll();
    return () => {
      active = false;
      controller.abort();
      window.clearTimeout(timer);
    };
    // The latest props and accepted version are read through refs during recovery.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, session.version, refresh]);

  const locked =
    busy ||
    !!pending ||
    unreadable ||
    !!session.remote_active_run ||
    (!!run && !run.cleanup?.reset_verified);
  const ready =
    loaded &&
    !reconnecting &&
    preflight?.ready &&
    preflight.enabled &&
    preflight.session_version === session.version &&
    !locked &&
    !dirty &&
    !teachingBusy &&
    session.status !== "running";
  const submit = async () => {
    if (!ready || inFlight.current || pendingRequest.current) return;
    inFlight.current = true;
    mutation.current += 1;
    setBusy(true);
    setError("");
    current.current.onLockChange(true);
    const request: Submission = {
      run_id: crypto.randomUUID(),
      session_id: id,
      expected_version: current.current.session.version,
    };
    try {
      if (preflight?.commissioning) {
        // Count durably BEFORE the existing POST; unknown outcomes stay counted.
        const report = await api<ServerReport>("/commissioning/report");
        commissioningReport.current = report;
        saveEvidence(
          sessionStorage,
          recordSubmission(readEvidence(sessionStorage, report), {
            ...request,
            plan_hash: preflight.plan_hash,
            document_id: documentId,
          }),
        );
      }
      // If durable local recovery cannot be saved, no request is transmitted.
      sessionStorage.setItem(requestKey(id), JSON.stringify(request));
      pendingRequest.current = request;
      setPending(request);
      const next = await api<NativeRun>("/runs", json(request));
      if (!alive.current || current.current.session.id !== id) return;
      acceptRun(next);
      clearSubmission();
      // Session refresh belongs to the read-only poll. Its failure cannot undo
      // this accepted submission or release the run reservation.
    } catch (cause) {
      if (!alive.current || current.current.session.id !== id) return;
      if (cause instanceof ApiError && [422, 503].includes(cause.status)) {
        // These are authoritative pre-submission rejections, not an unknown dispatch.
        clearSubmission();
        setError(cause.message);
      } else {
        setError(
          pendingRequest.current
            ? "Submission could not be confirmed. Keep this workflow open or return later. Check connection reads the original run; it never submits a second copy."
            : "The browser could not save recovery details. No run was submitted.",
        );
      }
    } finally {
      inFlight.current = false;
      if (alive.current) {
        setBusy(false);
        setRefresh((value) => value + 1);
      }
    }
  };
  const control = async (action: "pause" | "resume" | "cancel") => {
    if (!run || inFlight.current || reconnecting || !loaded) return;
    inFlight.current = true;
    mutation.current += 1;
    setBusy(true);
    setError("");
    try {
      const next = await api<NativeRun>(
        `/runs/${run.run_id}/control`,
        json({
          command_id: crypto.randomUUID(),
          expected_version: run.version,
          action,
        }),
      );
      if (alive.current && current.current.session.id === id) acceptRun(next);
    } catch {
      if (alive.current) {
        setLoaded(false);
        setError(
          "The control response was not confirmed. Check connection to read the current run before requesting another action.",
        );
      }
    } finally {
      inFlight.current = false;
      if (alive.current) {
        setBusy(false);
        setRefresh((value) => value + 1);
      }
    }
  };
  const state = run?.snapshot?.native_state;
  const studio = state?.studio;

  return (
    <section
      className={s.panel}
      aria-label="Native Matterix workflow"
      data-testid="native-studio-run"
    >
      <header className={s.heading}>
        <h2>Matterix simulation</h2>
        <span className={s.badge}>
          {run?.evidence === "native"
            ? "Native observations received"
            : "No native result yet"}
        </span>
      </header>
      <div className={s.preflight} aria-live="polite">
        <strong>
          {!loaded
            ? reconnecting
              ? "Native availability could not be confirmed"
              : "Checking the saved workflow…"
            : preflight?.ready
              ? "Saved workflow is compatible"
              : "Native execution is unavailable for this saved workflow"}
        </strong>
        <p>
          {preflight?.message ??
            "Checking worker availability and the saved plan."}
        </p>
        {preflight && (
          <small>
            {INSTRUMENT_NAMES[preflight.instrument]} · Saved revision{" "}
            {preflight.session_version}
          </small>
        )}
        {!!preflight?.issues.length && (
          <ul>
            {preflight.issues.map((issue, index) => (
              <li key={`${issue.code}-${index}`}>
                {issue.step == null ? "" : `Step ${issue.step + 1}: `}
                {issue.message}
              </li>
            ))}
          </ul>
        )}
      </div>
      {dirty && (
        <p className={s.notice}>
          Save your changes to check and run this exact workflow.
        </p>
      )}
      {preflight?.commissioning && (
        <p className={s.notice}>
          Operator commissioning window. This access applies to an explicitly
          approved saved workflow; general learner execution is still awaiting
          qualification.
        </p>
      )}
      {session.status === "running" && (
        <p className={s.notice}>
          Pause or finish the teaching simulation before starting a native run.
        </p>
      )}
      {reconnecting && (
        <p className={s.warning} role="status">
          <AlertTriangle size={16} /> Connection checks are delayed. Showing the
          last confirmed native state.
        </p>
      )}
      {(error || pollingError) && (
        <p className={s.warning} role="alert">
          {error || pollingError}
        </p>
      )}
      {(pending || unreadable) && (
        <p className={s.warning}>
          A previous submission is unresolved. Editing and another native
          submission stay locked until the original request is reconciled.
        </p>
      )}
      <div className={s.actions}>
        <button
          className={s.primary}
          disabled={!ready}
          onClick={() => void submit()}
        >
          <Play size={16} />
          {busy
            ? "Submitting…"
            : run?.cleanup?.reset_verified
              ? "Run saved workflow again"
              : "Run saved workflow in Matterix"}
        </button>
        <button
          disabled={busy}
          onClick={() => {
            setError("");
            setRefresh((value) => value + 1);
          }}
        >
          <RefreshCw size={16} /> Check connection
        </button>
      </div>
      {run ? (
        <>
          {preflight && run.plan_hash !== preflight.plan_hash && (
            <p className={s.notice}>
              These native observations belong to an earlier saved design. Run
              the current saved workflow to observe your changes.
            </p>
          )}
          <div className={s.runSummary}>
            <strong>{labels[run.status] ?? run.status}</strong>
            <span>
              {run.completed_steps} / {run.total_steps} saved actions confirmed
            </span>
          </div>
          <progress
            aria-label="Native workflow confirmed progress"
            value={run.completed_steps}
            max={run.total_steps || 1}
          />
          {!!run.reason && <p className={s.warning}>{run.reason}</p>}
          {run.status === "outcome_unknown" && (
            <p className={s.warning}>
              The simulator outcome is unknown. This run will not restart
              automatically; an operator must reconcile it and verify reset.
            </p>
          )}
          {run.stale_seconds > 10 && !terminalRuns.has(run.status) && (
            <p className={s.warning}>
              The last native observation is at least {run.stale_seconds}{" "}
              seconds old. Progress is not estimated.
            </p>
          )}
          <IsaacViewport
            run={run}
            onEvidence={preflight?.commissioning ? observeVideo : undefined}
          />
          <div className={s.observations}>
            {(["stock", "A1", "A2", "A3"] as const).map((well) => (
              <div key={well}>
                <span>{well === "stock" ? "Stock" : `Well ${well}`}</span>
                <strong>{amount(state?.well_volumes_ul[well])}</strong>
              </div>
            ))}
            <div>
              <span>Liquid in pipette</span>
              <strong>{amount(state?.pipette_volume_ul)}</strong>
            </div>
            <div>
              <span>Tip attached</span>
              <strong>
                {state?.tip_attached == null
                  ? "Not observed"
                  : state.tip_attached
                    ? "Yes"
                    : "No"}
              </strong>
            </div>
          </div>
          {studio && (
            <div className={s.nativeDetail}>
              <strong>
                {INSTRUMENT_NAMES[studio.instrument]} · Native motion and
                semantic liquid accounting
              </strong>
              <p>
                Native action {studio.native_action_index} /{" "}
                {studio.native_action_count}: {studio.native_action}. Waste:{" "}
                {amount(studio.waste_volume_ul)}.
              </p>
              <p>
                Observed deck:{" "}
                {Object.entries(studio.labware_slots)
                  .map(([item, slot]) => `${item} ${slot}`)
                  .join(" · ")}
                .
              </p>
            </div>
          )}
          <p className={s.metadata}>
            Run {run.run_id}
            {run.snapshot
              ? ` · Observed ${new Date(run.snapshot.observed_at).toLocaleString()}`
              : " · Awaiting native observations"}
          </p>
          {terminalRuns.has(run.status) && (
            <p className={run.cleanup?.reset_verified ? s.confirmed : s.notice}>
              {run.cleanup?.reset_verified ? (
                <>
                  <CheckCircle2 size={16} /> Native reset verified. The saved
                  workflow can be checked for another run.
                </>
              ) : (
                "The workflow remains reserved until the worker verifies native cleanup and reset."
              )}
            </p>
          )}
          <div className={s.actions}>
            {run.status === "queued" && (
              <button
                disabled={busy || reconnecting || !loaded}
                onClick={() => void control("cancel")}
              >
                Cancel queued native run
              </button>
            )}
            {run.status === "running" &&
              run.supported_controls.includes("pause") && (
                <button
                  disabled={busy || reconnecting || !loaded}
                  onClick={() => void control("pause")}
                >
                  Request native pause
                </button>
              )}
            {run.status === "paused" &&
              run.supported_controls.includes("resume") && (
                <button
                  disabled={busy || reconnecting || !loaded}
                  onClick={() => void control("resume")}
                >
                  Request native resume
                </button>
              )}
          </div>
        </>
      ) : (
        <div className={s.empty}>
          <Monitor size={23} />
          <p>Live Isaac video appears here when the saved run starts.</p>
        </div>
      )}
      {preflight?.commissioning && (
        <details>
          <summary>Acceptance evidence</summary>
          <div className={s.actions}>
            <button
              disabled={exporting}
              onClick={() => void downloadEvidence()}
            >
              {exporting
                ? "Preparing download…"
                : "Download acceptance evidence"}
            </button>
          </div>
          {evidenceError && (
            <p className={s.warning} role="status">
              {evidenceError}
            </p>
          )}
        </details>
      )}
      <p className={s.boundary}>
        Native simulation, not physical instrument control. Liquid amounts use
        semantic accounting, not validated fluid physics or chemistry. Video is
        view-only; closing this page does not cancel a run.
      </p>
    </section>
  );
}
