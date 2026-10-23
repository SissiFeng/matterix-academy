import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  ArrowLeftRight,
  Box,
  Check,
  Circle,
  CircleAlert,
  FlaskConical,
  Layers3,
  Plus,
  RefreshCw,
  Unplug,
} from "lucide-react";
import { api, ApiError, json } from "./api";
import type { Session } from "./types";
import {
  capabilityLabels,
  connections,
  draftOf,
  type Device,
  type DeviceDraft,
  type ReadinessCheck,
  type WorkspaceView,
} from "./workcellTypes";
import s from "./Workcell.module.css";
import InstrumentStories from "./InstrumentStories";
import type { Instrument, Starter } from "./studioContent";

type Props = {
  view: WorkspaceView;
  name: string;
  onNavigate: (target: string) => void;
  onOpen: (session: Session) => void;
  onFirstLesson: () => void;
  onCreate: () => void;
  onDesign: (instrument: Instrument, starter: Starter) => void;
  creationBusy: boolean;
  onSessionsLoaded: (sessions: Session[]) => void;
  onSessionSaved: (session: Session) => void;
  registerLeaveGuard: (guard: (() => boolean) | null) => void;
};
const steps = [
  "Identify",
  "Connect",
  "Capabilities",
  "Create twin",
  "Validate",
];
const titles = {
  overview: "Your workcell, from intent to evidence.",
  onboard: "Bring a device into your workspace.",
  twin: "Two sides. One clear view.",
  readiness: "Know what is ready. See what is missing.",
  runs: "Every run has a story.",
};
const actionName = (action: Session["experiment"]["actions"][number]) =>
  `${capabilityLabels[action.kind]}${["aspirate", "dispense"].includes(action.kind) ? ` ${action.volume} µL · ${action.well}` : ""}`;
const when = (value: string) =>
  new Date(value).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

function Checks({ checks }: { checks: ReadinessCheck[] }) {
  return (
    <ul className={s.checks}>
      {checks.map((check) => (
        <li key={check.id} data-state={check.status}>
          {check.status === "passed" ? (
            <Check size={18} />
          ) : check.status === "failed" ? (
            <CircleAlert size={18} />
          ) : (
            <Circle size={18} />
          )}
          <div>
            <strong>{check.label}</strong>
            <p>{check.detail}</p>
          </div>
          <span>
            {check.status === "missing"
              ? "Unverified"
              : check.status === "passed"
                ? "Passed"
                : "Needs attention"}
          </span>
        </li>
      ))}
    </ul>
  );
}

function Pair({ device }: { device?: Device }) {
  return (
    <div className={s.pair}>
      <div>
        <span className={s.kicker}>PHYSICAL DEVICE</span>
        <strong>{device?.name || "Your Flex"}</strong>
        <span className={s.mutedStatus}>
          <Unplug size={13} /> Not connected
        </span>
      </div>
      <ArrowLeftRight className={s.pairArrow} size={26} aria-hidden="true" />
      <div>
        <span className={s.kicker}>DIGITAL REPRESENTATION</span>
        <strong>
          {device?.twin_session_id ? "Flex teaching twin" : "Not paired yet"}
        </strong>
        <span className={s.mutedStatus}>
          <Box size={13} />{" "}
          {device?.twin_session_id
            ? "Synthetic · saved state"
            : "Create a teaching twin"}
        </span>
      </div>
    </div>
  );
}

function DeckPreview({ session }: { session: Session }) {
  const labels: Record<string, string> = {
    tips: "TIP RACK",
    stock: "SOURCE",
    plate: "PLATE",
    waste: "WASTE",
  };
  return (
    <div
      className={s.deck}
      role="img"
      aria-label="Flex schematic of the saved teaching layout; physical geometry is unverified"
    >
      <div className={s.deckTitle}>
        <strong>FLEX</strong>
        <span>SCHEMATIC / TOP VIEW</span>
      </div>
      <div className={s.slots}>
        {[..."ABCD"].flatMap((row) =>
          [1, 2, 3].map((col) => {
            const slot = `${row}${col}`;
            const asset = Object.keys(session.experiment.layout).find(
              (key) => session.experiment.layout[key] === slot,
            );
            return (
              <div className={s.slot} key={slot} data-asset={asset}>
                <small>{slot}</small>
                {asset && (
                  <>
                    <div
                      className={
                        asset === "tips" || asset === "plate"
                          ? s.wells
                          : asset === "stock"
                            ? s.vial
                            : s.waste
                      }
                    >
                      {(asset === "tips" || asset === "plate") &&
                        Array.from({ length: 12 }, (_, i) => <i key={i} />)}
                    </div>
                    <span>{labels[asset]}</span>
                  </>
                )}
              </div>
            );
          }),
        )}
      </div>
      <div className={s.deckFoot}>
        <span>Teaching model</span>
        <span>Session revision {session.version}</span>
      </div>
    </div>
  );
}

export default function Workcell({
  view,
  name,
  onNavigate,
  onOpen,
  onFirstLesson,
  onCreate,
  onDesign,
  creationBusy,
  onSessionsLoaded,
  onSessionSaved,
  registerLeaveGuard,
}: Props) {
  const routeId = window.location.hash.split("/")[2] ?? "";
  const [devices, setDevices] = useState<Device[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selectedId, setSelectedId] = useState(view === "runs" ? "" : routeId);
  const [runId, setRunId] = useState(view === "runs" ? routeId : "");
  const [draft, setDraft] = useState<DeviceDraft>(draftOf());
  const [step, setStep] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [unresolved, setUnresolved] = useState(false);
  const pendingId = useRef(crypto.randomUUID());
  const alive = useRef(true);
  const inFlight = useRef(false);
  const mutating = useRef(false);
  const selected = devices.find((item) => item.id === selectedId);
  const run = sessions.find((item) => item.id === runId);
  const dirty =
    view === "onboard" &&
    JSON.stringify(draft) !== JSON.stringify(draftOf(selected));
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    registerLeaveGuard(
      () =>
        !mutating.current &&
        (!dirty || window.confirm("Leave without saving your device changes?")),
    );
    const leaving = (event: BeforeUnloadEvent) => {
      if (dirty || mutating.current) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", leaving);
    return () => {
      registerLeaveGuard(null);
      window.removeEventListener("beforeunload", leaving);
    };
  }, [dirty, registerLeaveGuard]);

  const accept = useCallback(
    (device: Device) => {
      setDevices((items) => [
        device,
        ...items.filter((item) => item.id !== device.id),
      ]);
      setSelectedId(device.id);
      setDraft(draftOf(device));
      if (device.session) {
        setSessions((items) => [
          device.session!,
          ...items.filter((item) => item.id !== device.session!.id),
        ]);
        onSessionSaved(device.session);
      }
      window.history.replaceState({}, "", `/#/${view}/${device.id}`);
    },
    [view, onSessionSaved],
  );

  const load = async (initial = false) => {
    if (inFlight.current) return;
    if (
      !initial &&
      dirty &&
      !window.confirm("Reload and discard your unsaved device changes?")
    )
      return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    try {
      const [nextDevices, recentSessions] = await Promise.all([
        api<Device[]>("/devices"),
        api<Session[]>("/sessions"),
      ]);
      // A paired trial may be older than the recent-session list's 50-record window.
      const byId = new Map(recentSessions.map((item) => [item.id, item]));
      for (const device of nextDevices) {
        if (device.session && !byId.has(device.session.id))
          byId.set(device.session.id, device.session);
      }
      if (view === "runs" && runId && !byId.has(runId)) {
        const older = await api<Session>(
          `/sessions/${encodeURIComponent(runId)}`,
        );
        if (older.engine !== "teaching" || older.evidence !== "synthetic")
          throw new Error(
            "Open native simulation runs from the Simulation lab.",
          );
        byId.set(older.id, older);
      }
      const nextSessions = [...byId.values()];
      if (!alive.current) return;
      setDevices(nextDevices);
      setSessions(nextSessions);
      onSessionsLoaded(nextSessions);
      const id = selectedId || (view === "onboard" ? "" : nextDevices[0]?.id);
      const device = nextDevices.find((item) => item.id === id);
      if (id && !device)
        setError(
          "This device is unavailable in your workspace. Select another device or add one.",
        );
      if (device) {
        setSelectedId(device.id);
        setDraft(draftOf(device));
        setStep(device.twin_session_id ? 4 : device.stage);
      } else if (view === "onboard" && !id) {
        setDraft(draftOf());
        setStep(0);
      }
      if (view === "runs" && !runId) setRunId(nextSessions[0]?.id ?? "");
      if (
        view === "runs" &&
        runId &&
        !nextSessions.some((item) => item.id === runId)
      )
        setError("This teaching run is unavailable in your workspace.");
      setLoaded(true);
      setUnresolved(false);
    } catch (e) {
      if (alive.current) {
        setError((e as Error).message);
        setUnresolved(true);
      }
    } finally {
      inFlight.current = false;
      if (alive.current) setBusy(false);
    }
  };
  useEffect(() => {
    void load(true);
  }, []);

  const chooseDevice = (id: string) => {
    if (
      inFlight.current ||
      (dirty && !window.confirm("Discard your unsaved device changes?"))
    )
      return;
    const device = devices.find((item) => item.id === id);
    setSelectedId(id);
    setDraft(draftOf(device));
    setStep(device ? (device.twin_session_id ? 4 : device.stage) : 0);
    setError("");
    setNotice("");
    pendingId.current = crypto.randomUUID();
    window.history.replaceState({}, "", `/#/${view}${id ? `/${id}` : ""}`);
  };
  const mutate = async (twin = false) => {
    if (inFlight.current || unresolved) return;
    inFlight.current = true;
    mutating.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    const id = selected?.id ?? pendingId.current;
    try {
      const next = await api<Device>(
        `/devices/${id}${twin ? "/twin" : ""}`,
        json(
          twin
            ? { expected_version: selected!.version }
            : {
                ...draft,
                stage: Math.min(3, step + 1),
                expected_version: selected?.version ?? 0,
              },
          twin ? "POST" : "PUT",
        ),
      );
      if (!alive.current) return;
      accept(next);
      setStep(twin ? 4 : Math.min(4, step + 1));
      setNotice(
        twin
          ? "Teaching twin paired. Physical validation is still required."
          : "Device progress saved.",
      );
    } catch (e) {
      if (!alive.current) return;
      setError((e as Error).message);
      if (!(e instanceof ApiError) || e.status === 409 || e.status >= 500) {
        // Reconcile a lost receipt once; never replay a create or overwrite a stale revision.
        try {
          const current = await api<Device>(`/devices/${id}`);
          if (!alive.current) return;
          accept(current);
          setStep(current.twin_session_id ? 4 : current.stage);
          setNotice(
            "Reloaded the saved device. Review its current state before continuing.",
          );
        } catch (reloadError) {
          if (alive.current) {
            setUnresolved(
              !(reloadError instanceof ApiError && reloadError.status === 404),
            );
            setNotice(
              "No saved receipt could be loaded. Refresh the workspace before continuing.",
            );
            if (!(
              reloadError instanceof ApiError && reloadError.status === 404
            )) {
              setSelectedId(id);
              window.history.replaceState({}, "", `/#/${view}/${id}`);
            }
          }
        }
      }
    } finally {
      inFlight.current = false;
      mutating.current = false;
      if (alive.current) setBusy(false);
    }
  };
  const patch = (change: Partial<DeviceDraft>) =>
    setDraft((current) => ({ ...current, ...change }));
  const selectedRoute = (target: string) =>
    onNavigate(`${target}${selected ? `/${selected.id}` : ""}`);
  const workcells = [...new Set(devices.map((item) => item.workcell))];
  const paired = devices.filter((item) => item.twin_session_id);
  const missingPhysical =
    selected?.checks.filter((check) => check.scope === "physical") ?? [];
  const chooseRun = (id: string) => {
    setRunId(id);
    window.history.replaceState({}, "", `/#/runs/${id}`);
  };

  return (
    <div className={s.page}>
      <header className={s.heading}>
        <div>
          <span className={s.kicker}>
            WORKCELL /{" "}
            {view === "readiness" ? "SIM → REAL" : view.toUpperCase()}
          </span>
          <h1>
            {view === "overview"
              ? `Welcome to the lab, ${name}.`
              : titles[view]}
          </h1>
          <p>
            {view === "overview"
              ? "Meet the instruments, borrow a workflow, then make it your own."
              : view === "onboard"
                ? "Five steps from a device record to an honest validation checklist."
                : view === "twin"
                  ? "Compare saved teaching state with what is known about the physical device."
                  : view === "readiness"
                    ? "Teaching progress and physical readiness are assessed separately."
                    : "Trace saved teaching steps alongside the physical observations still to come."}
          </p>
        </div>
        <button
          className={s.iconButton}
          disabled={busy}
          onClick={() => void load()}
          aria-label="Refresh workspace"
        >
          <RefreshCw size={17} />
        </button>
      </header>
      {error && (
        <div className={s.alert} role="alert">
          {error}
          <button onClick={() => void load()} disabled={busy}>
            Reload workspace
          </button>
        </div>
      )}
      {notice && (
        <p className={s.notice} role="status">
          {notice}
        </p>
      )}
      {!loaded ? (
        <p className={s.empty}>Loading your saved workspace…</p>
      ) : (
        <>
          {view === "overview" ? (
            <>
              <InstrumentStories
                onDesign={onDesign}
                busy={creationBusy}
                compact
              />
              <details className={s.setupDetails}>
                <summary>Workcell setup and connection status</summary>
                <section className={s.hero}>
                  <div>
                    <span className={s.kicker}>CURRENT OPERATING STATE</span>
                    <h2>
                      Practice is available.
                      <br />
                      <em>Physical execution is not connected.</em>
                    </h2>
                    <p>
                      Build your workcell here, then use its missing evidence as
                      a guide to qualification.
                    </p>
                    <button
                      className={s.primary}
                      onClick={() => onNavigate("onboard")}
                    >
                      Onboard a device <ArrowRight size={16} />
                    </button>
                  </div>
                  <div className={s.lifecycle}>
                    {[
                      "01 / ONBOARD",
                      "02 / TWIN",
                      "03 / VALIDATE",
                      "04 / RUN & LEARN",
                    ].map((label, i) => (
                      <button
                        key={label}
                        onClick={() =>
                          onNavigate(
                            ["onboard", "twin", "readiness", "runs"][i],
                          )
                        }
                      >
                        <span>{label}</span>
                        {i === 2 ? (
                          <CircleAlert size={20} />
                        ) : (
                          <ArrowRight size={20} />
                        )}
                      </button>
                    ))}
                  </div>
                </section>
              </details>
              <div className={s.metrics}>
                <div>
                  <span>Registered devices</span>
                  <strong>{devices.length}</strong>
                  <small>Manually declared · connectivity unverified</small>
                </div>
                <div>
                  <span>Paired teaching twins</span>
                  <strong>{paired.length}</strong>
                  <small>Synthetic models · physical sync unverified</small>
                </div>
                <div>
                  <span>Teaching experiments</span>
                  <strong>{sessions.length}</strong>
                  <small>
                    {
                      sessions.filter(
                        (item) =>
                          item.status === "completed" &&
                          item.assessment?.passed &&
                          item.assessment.scope !== "model-checks",
                      ).length
                    }{" "}
                    with a saved passing goal
                  </small>
                </div>
              </div>
              <div className={s.sectionHeading}>
                <h2>Your workcells</h2>
                <span>{workcells.length} registered</span>
              </div>
              {workcells.length ? (
                <div className={s.workcells}>
                  {workcells.map((cell) => (
                    <section className={s.workcell} key={cell}>
                      <div className={s.sectionHeading}>
                        <h3>{cell}</h3>
                        <span className={s.tag}>Needs qualification</span>
                      </div>
                      {devices
                        .filter((item) => item.workcell === cell)
                        .map((device) => (
                          <button
                            className={s.deviceRow}
                            key={device.id}
                            onClick={() =>
                              onNavigate(
                                `${device.twin_session_id ? "twin" : "onboard"}/${device.id}`,
                              )
                            }
                          >
                            <Box size={22} />
                            <span>
                              <strong>{device.name}</strong>
                              <small>
                                Opentrons Flex ↔{" "}
                                {device.twin_session_id
                                  ? "Teaching twin"
                                  : "No twin yet"}
                              </small>
                            </span>
                            <ArrowRight size={16} />
                          </button>
                        ))}
                    </section>
                  ))}
                </div>
              ) : (
                <div className={s.empty}>
                  <Layers3 size={30} />
                  <h3>Your first workcell starts with one device.</h3>
                  <p>
                    Register your Flex and choose a connection plan. No network
                    discovery or device commands are sent.
                  </p>
                  <button
                    className={s.secondary}
                    onClick={() => onNavigate("onboard")}
                  >
                    Add your first device <Plus size={16} />
                  </button>
                </div>
              )}
              <section className={s.practice}>
                <div>
                  <span className={s.kicker}>LEARN WHILE YOU PREPARE</span>
                  <h2>A small transfer. A useful first step.</h2>
                  <p>
                    Explore the Flex, predict liquid movement and inspect every
                    teaching step.
                  </p>
                </div>
                <div className={s.actions}>
                  <button className={s.primary} onClick={onFirstLesson}>
                    Start learning Flex <ArrowRight size={16} />
                  </button>
                  <button className={s.secondary} onClick={onCreate}>
                    Start an experiment
                  </button>
                </div>
              </section>
              <div className={s.sectionHeading}>
                <h2>Recent teaching activity</h2>
                <button
                  className={s.textButton}
                  onClick={() => onNavigate("runs")}
                >
                  View runs <ArrowRight size={14} />
                </button>
              </div>
              {sessions.slice(0, 4).map((item) => (
                <button
                  className={s.activity}
                  key={item.id}
                  onClick={() => onNavigate(`runs/${item.id}`)}
                >
                  <FlaskConical size={18} />
                  <span>
                    <strong>{item.experiment.title}</strong>
                    <small>
                      {when(item.created_at)} · {item.cursor} /{" "}
                      {item.experiment.actions.length} steps · {item.status}
                    </small>
                  </span>
                  <ArrowRight size={15} />
                </button>
              ))}
              {!sessions.length && (
                <p className={s.muted}>Your saved trials will appear here.</p>
              )}
            </>
          ) : view === "runs" ? (
            <>
              <div className={s.toolbar}>
                <label>
                  Teaching experiment
                  <select
                    value={runId}
                    onChange={(e) => chooseRun(e.target.value)}
                  >
                    <option value="">Choose an experiment</option>
                    {sessions.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.experiment.title} · {item.id.slice(0, 8)}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  className={s.secondary}
                  onClick={() => onNavigate("sim")}
                >
                  Native simulation runs <ArrowRight size={16} />
                </button>
              </div>
              {run ? (
                <>
                  <div className={s.runHeading}>
                    <div>
                      <span className={s.kicker}>
                        RUN / {run.id.slice(0, 8)}
                      </span>
                      <h2>{run.experiment.title}</h2>
                      <p>
                        Saved revision {run.version} · {when(run.created_at)} ·{" "}
                        {run.status}
                      </p>
                    </div>
                    <button className={s.primary} onClick={() => onOpen(run)}>
                      Open teaching experiment <ArrowRight size={16} />
                    </button>
                  </div>
                  <div className={s.comparisonSummary}>
                    <div>
                      <span>Teaching progress</span>
                      <strong>
                        {run.cursor} / {run.experiment.actions.length} steps
                      </strong>
                    </div>
                    <div>
                      <span>Physical trace</span>
                      <strong>Not recorded</strong>
                    </div>
                    <div>
                      <span>Timing / state deviation</span>
                      <strong>Not comparable</strong>
                    </div>
                  </div>
                  <div className={s.tableScroll}>
                    <table className={s.trace}>
                      <caption>
                        Teaching ↔ physical run comparison · current attempt
                      </caption>
                      <thead>
                        <tr>
                          <th>Workflow step</th>
                          <th>Teaching observation</th>
                          <th>Physical observation</th>
                        </tr>
                      </thead>
                      <tbody>
                        {run.experiment.actions.map((action, index) => {
                          const event = run.events.find(
                            (item) => item.step === index + 1,
                          );
                          return (
                            <tr key={index}>
                              <th>
                                <small>
                                  {String(index + 1).padStart(2, "0")}
                                </small>
                                {actionName(action)}
                              </th>
                              <td data-state={event?.level}>
                                <strong>
                                  {event
                                    ? event.level === "success"
                                      ? "Completed"
                                      : "Failed"
                                    : "Not executed"}
                                </strong>
                                <span>
                                  {event?.message ??
                                    "Waiting for a teaching step"}
                                </span>
                                {event?.hint && <small>{event.hint}</small>}
                              </td>
                              <td>
                                <span>Not recorded</span>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  <p className={s.footnote}>
                    The teaching runner does not record step durations. No
                    timing deviation or physical agreement is inferred.
                  </p>
                  {run.attempts.length > 0 && (
                    <section className={s.panel}>
                      <h2>Previous attempts</h2>
                      <p>
                        Retained summaries only; earlier step traces are not
                        available.
                      </p>
                      {run.attempts.map((attempt, index) => (
                        <div className={s.attempt} key={index}>
                          <strong>Attempt {index + 1}</strong>
                          <span>
                            {attempt.status} · {attempt.steps} steps
                          </span>
                          <span>
                            {run.experiment.course_id === "workflow-sandbox"
                              ? !attempt.assessment
                                ? "Sequence incomplete"
                                : attempt.assessment.passed
                                  ? "Model checks passed"
                                  : "Review model checks"
                              : attempt.assessment?.passed
                                ? "Teaching goal passed"
                                : "Goal not reached"}
                          </span>
                        </div>
                      ))}
                    </section>
                  )}
                  <div className={s.actions}>
                    <button
                      className={s.secondary}
                      onClick={() => {
                        const device = devices.find(
                          (item) => item.twin_session_id === run.id,
                        );
                        onNavigate(device ? `twin/${device.id}` : "onboard");
                      }}
                    >
                      Return to the twin <ArrowRight size={16} />
                    </button>
                  </div>
                </>
              ) : (
                <div className={s.empty}>
                  <FlaskConical size={30} />
                  <h2>No teaching run selected.</h2>
                  <p>Select a saved experiment or start your first trial.</p>
                  <button className={s.primary} onClick={onCreate}>
                    Start an experiment <ArrowRight size={16} />
                  </button>
                </div>
              )}
            </>
          ) : (
            <>
              <div className={s.toolbar}>
                <label>
                  Device / workcell
                  <select
                    value={selectedId}
                    disabled={busy}
                    onChange={(e) => chooseDevice(e.target.value)}
                  >
                    <option value="">
                      {view === "onboard" ? "New device" : "Select a device"}
                    </option>
                    {devices.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name} / {item.workcell}
                      </option>
                    ))}
                  </select>
                </label>
                {view === "onboard" ? (
                  <button
                    className={s.secondary}
                    onClick={() => chooseDevice("")}
                    disabled={busy}
                  >
                    <Plus size={16} /> New device
                  </button>
                ) : (
                  <button
                    className={s.secondary}
                    onClick={() => selectedRoute("onboard")}
                  >
                    Edit onboarding <ArrowRight size={16} />
                  </button>
                )}
              </div>
              {view === "onboard" ? (
                <>
                  <ol
                    className={s.stepper}
                    aria-label="Device onboarding steps"
                  >
                    {steps.map((label, index) => (
                      <li key={label}>
                        <button
                          aria-current={step === index ? "step" : undefined}
                          disabled={
                            busy ||
                            (dirty && index > step) ||
                            index >
                              (selected?.twin_session_id
                                ? 4
                                : (selected?.stage ?? 0))
                          }
                          onClick={() => setStep(index)}
                        >
                          <span>
                            {index < step ? <Check size={14} /> : index + 1}
                          </span>
                          {label}
                        </button>
                      </li>
                    ))}
                  </ol>
                  <div className={s.wizard}>
                    <section className={s.wizardMain}>
                      <span className={s.kicker}>STEP {step + 1} / 5</span>
                      <h2>
                        {
                          [
                            "Identify your physical device",
                            "Choose a connection plan",
                            "Describe its intended capabilities",
                            "Pair a teaching twin",
                            "Review the evidence",
                          ][step]
                        }
                      </h2>
                      {step === 0 && (
                        <>
                          <p>
                            Register a device manually. A saved identity does
                            not mean the device has been detected.
                          </p>
                          <label>
                            Device name
                            <input
                              value={draft.name}
                              maxLength={80}
                              placeholder="e.g. Flex 01"
                              onChange={(e) => patch({ name: e.target.value })}
                              disabled={busy}
                            />
                          </label>
                          <label>
                            Workcell name
                            <input
                              value={draft.workcell}
                              maxLength={80}
                              onChange={(e) =>
                                patch({ workcell: e.target.value })
                              }
                              disabled={busy}
                            />
                          </label>
                          <label>
                            Device model
                            <select value={draft.model} disabled>
                              <option value="opentrons_flex">
                                Opentrons Flex · teaching template available
                              </option>
                            </select>
                          </label>
                        </>
                      )}
                      {step === 1 && (
                        <>
                          <p>
                            Select the adapter you intend to qualify. These
                            choices record a plan; they do not connect to an
                            instrument.
                          </p>
                          <fieldset className={s.options}>
                            <legend>Planned connection</legend>
                            {Object.entries(connections).map(
                              ([key, option]) => (
                                <label
                                  key={key}
                                  data-selected={draft.connection === key}
                                >
                                  <input
                                    type="radio"
                                    name="connection"
                                    value={key}
                                    checked={draft.connection === key}
                                    disabled={busy}
                                    onChange={() => patch({ connection: key })}
                                  />
                                  <span>
                                    <strong>{option.name}</strong>
                                    <small>{option.detail}</small>
                                  </span>
                                </label>
                              ),
                            )}
                          </fieldset>
                          <button
                            className={s.textButton}
                            onClick={() => onNavigate("connector")}
                          >
                            Explore how connectors work <ArrowRight size={14} />
                          </button>
                        </>
                      )}
                      {step === 2 && (
                        <>
                          <p>
                            Declare the operations this device is intended to
                            support. Hardware support remains unverified.
                          </p>
                          <fieldset className={s.options}>
                            <legend>Declared capabilities</legend>
                            {Object.entries(capabilityLabels).map(
                              ([key, label]) => (
                                <label
                                  key={key}
                                  data-selected={draft.capabilities.includes(
                                    key,
                                  )}
                                >
                                  <input
                                    type="checkbox"
                                    checked={draft.capabilities.includes(key)}
                                    disabled={busy}
                                    onChange={(e) =>
                                      patch({
                                        capabilities: e.target.checked
                                          ? [...draft.capabilities, key]
                                          : draft.capabilities.filter(
                                              (value) => value !== key,
                                            ),
                                      })
                                    }
                                  />
                                  <span>
                                    <strong>{label}</strong>
                                    <small>
                                      {[
                                        "pickup",
                                        "aspirate",
                                        "dispense",
                                        "drop",
                                      ].includes(key)
                                        ? "Available in the teaching model"
                                        : "Not evaluated by the teaching model"}
                                    </small>
                                  </span>
                                </label>
                              ),
                            )}
                          </fieldset>
                        </>
                      )}
                      {step === 3 && (
                        <>
                          <p>
                            Pair this record with a saved Flex serial-dilution
                            experiment. It uses ideal liquid bookkeeping and a
                            schematic deck.
                          </p>
                          <Pair device={selected} />
                          <div className={s.inset}>
                            <strong>What this creates</strong>
                            <p>
                              A persistent teaching session that you can edit,
                              run and review. Geometry, calibration, live state
                              synchronization and physical execution remain
                              unverified.
                            </p>
                          </div>
                        </>
                      )}
                      {step === 4 && selected && (
                        <>
                          <p>
                            {selected.name} is paired with a teaching model. Use
                            these checks to plan the next qualification work.
                          </p>
                          <Checks checks={selected.checks} />
                          <div className={s.actions}>
                            <button
                              className={s.primary}
                              onClick={() => selectedRoute("twin")}
                            >
                              Open twin <ArrowRight size={16} />
                            </button>
                            <button
                              className={s.secondary}
                              onClick={() => selectedRoute("readiness")}
                            >
                              Review Sim → Real
                            </button>
                          </div>
                        </>
                      )}
                      {step < 4 && (
                        <div className={s.wizardActions}>
                          <button
                            className={s.textButton}
                            disabled={step === 0 || busy}
                            onClick={() => setStep((current) => current - 1)}
                          >
                            <ArrowLeft size={16} /> Back
                          </button>
                          <button
                            className={s.primary}
                            disabled={
                              busy ||
                              unresolved ||
                              (step === 0 &&
                                (!draft.name.trim() ||
                                  !draft.workcell.trim())) ||
                              (step === 1 && !draft.connection) ||
                              (step === 2 && !draft.capabilities.length)
                            }
                            onClick={() =>
                              step === 3 && selected?.twin_session_id
                                ? setStep(4)
                                : void mutate(step === 3)
                            }
                          >
                            {busy
                              ? "Saving…"
                              : step === 3
                                ? selected?.twin_session_id
                                  ? "Review validation"
                                  : "Create teaching twin"
                                : "Save and continue"}
                            <ArrowRight size={16} />
                          </button>
                        </div>
                      )}
                    </section>
                    <aside className={s.wizardAside}>
                      <Box size={30} />
                      <span className={s.kicker}>YOUR DEVICE RECORD</span>
                      <h3>{draft.name || "A new Flex"}</h3>
                      <p>{draft.workcell}</p>
                      <dl>
                        <dt>Identity</dt>
                        <dd>Manually declared</dd>
                        <dt>Connection plan</dt>
                        <dd>
                          {connections[draft.connection]?.name ??
                            "Not selected"}
                        </dd>
                        <dt>Capabilities</dt>
                        <dd>{draft.capabilities.length} declared</dd>
                        <dt>Physical readiness</dt>
                        <dd>Unverified</dd>
                      </dl>
                      <span className={s.saved}>
                        {selected
                          ? `Saved revision ${selected.version} · ${when(selected.updated_at)}`
                          : "Not saved yet"}
                        {dirty ? " · Unsaved changes" : ""}
                      </span>
                    </aside>
                  </div>
                </>
              ) : !selected ? (
                <div className={s.empty}>
                  <Box size={30} />
                  <h2>Select or onboard a device.</h2>
                  <p>
                    A device record keeps the physical identity and teaching
                    twin together.
                  </p>
                  <button
                    className={s.primary}
                    onClick={() => onNavigate("onboard")}
                  >
                    Onboard a device <ArrowRight size={16} />
                  </button>
                </div>
              ) : view === "twin" ? (
                <>
                  <Pair device={selected} />
                  {selected.session ? (
                    <>
                      <div className={s.twinGrid}>
                        <section className={s.canvas}>
                          <div className={s.sectionHeading}>
                            <h2>{selected.name}</h2>
                            <span className={s.tag}>
                              Teaching state · not live
                            </span>
                          </div>
                          <DeckPreview session={selected.session} />
                          <div className={s.canvasActions}>
                            <button
                              className={s.primary}
                              onClick={() => onOpen(selected.session!)}
                            >
                              Open teaching trial <ArrowRight size={16} />
                            </button>
                            <button
                              className={s.textButton}
                              onClick={() => selectedRoute("readiness")}
                            >
                              Check readiness <ArrowRight size={14} />
                            </button>
                          </div>
                        </section>
                        <aside className={s.statePanel}>
                          <span className={s.kicker}>PHYSICAL ↔ DIGITAL</span>
                          <h2>State difference</h2>
                          <p>
                            Physical state has not been observed. Differences
                            cannot be calculated.
                          </p>
                          <div className={s.stateHead}>
                            <span>Property</span>
                            <span>Teaching</span>
                            <span>Physical</span>
                          </div>
                          {[
                            [
                              "Source",
                              `${selected.session.state.wells.stock.volume} µL`,
                            ],
                            [
                              "Well A1",
                              `${selected.session.state.wells.A1.volume} µL`,
                            ],
                            [
                              "Pipette",
                              `${selected.session.state.pipette.volume} µL`,
                            ],
                            [
                              "Tip attached",
                              selected.session.state.pipette.tip ? "Yes" : "No",
                            ],
                            [
                              "Tips remaining",
                              String(96 - selected.session.state.tips_used),
                            ],
                            ["Deck", "Saved layout"],
                            ["Calibration", "Not modeled"],
                          ].map(([label, value]) => (
                            <div className={s.stateRow} key={label}>
                              <strong>{label}</strong>
                              <span>{value}</span>
                              <span>Unknown</span>
                            </div>
                          ))}
                          <p className={s.footnote}>
                            Saved session revision {selected.session.version}.
                            Refresh to retrieve the latest saved state.
                          </p>
                        </aside>
                      </div>
                      <section className={s.panel}>
                        <div className={s.sectionHeading}>
                          <h2>Teaching timeline</h2>
                          <button
                            className={s.textButton}
                            onClick={() =>
                              onNavigate(`runs/${selected.session!.id}`)
                            }
                          >
                            Compare run <ArrowRight size={14} />
                          </button>
                        </div>
                        {selected.session.events.length ? (
                          <ol className={s.timeline}>
                            {selected.session.events.map((event, index) => (
                              <li key={index} data-state={event.level}>
                                <span>
                                  {String(event.step).padStart(2, "0")}
                                </span>
                                <div>
                                  <strong>
                                    {event.level === "error"
                                      ? "Failed"
                                      : "Completed"}
                                  </strong>
                                  <p>{event.message}</p>
                                </div>
                              </li>
                            ))}
                          </ol>
                        ) : (
                          <p>No teaching steps have been executed yet.</p>
                        )}
                      </section>
                    </>
                  ) : (
                    <div className={s.empty}>
                      <h2>This device has no teaching twin yet.</h2>
                      <button
                        className={s.primary}
                        onClick={() => selectedRoute("onboard")}
                      >
                        Continue onboarding <ArrowRight size={16} />
                      </button>
                    </div>
                  )}
                </>
              ) : (
                <>
                  <section className={s.readinessHero}>
                    <div>
                      <span className={s.kicker}>
                        SIM → REAL / {selected.name}
                      </span>
                      <h2>Physical readiness is unverified.</h2>
                      <p>
                        {missingPhysical.length} physical checks need evidence.
                        Passing a teaching trial does not clear these checks.
                      </p>
                    </div>
                    <div className={s.readinessCount}>
                      <strong>{missingPhysical.length}</strong>
                      <span>evidence gaps</span>
                    </div>
                  </section>
                  <section className={s.panel}>
                    <div className={s.sectionHeading}>
                      <h2>01 / Teaching evidence</h2>
                      <span className={s.tag}>Synthetic only</span>
                    </div>
                    <Checks
                      checks={selected.checks.filter(
                        (check) => check.scope === "teaching",
                      )}
                    />
                  </section>
                  <section className={s.panel}>
                    <div className={s.sectionHeading}>
                      <h2>02 / Physical qualification</h2>
                      <span className={s.tag}>Not connected</span>
                    </div>
                    <Checks checks={missingPhysical} />
                  </section>
                  <div className={s.execution}>
                    <div className={s.actions}>
                      {selected.session ? (
                        <button
                          className={s.primary}
                          onClick={() => onOpen(selected.session!)}
                        >
                          Open teaching trial <ArrowRight size={16} />
                        </button>
                      ) : (
                        <button
                          className={s.primary}
                          onClick={() => selectedRoute("onboard")}
                        >
                          Create a teaching twin <ArrowRight size={16} />
                        </button>
                      )}
                      <button
                        className={s.secondary}
                        disabled
                        aria-describedby="physical-reason"
                      >
                        Execute on real lab
                      </button>
                    </div>
                    <p id="physical-reason">
                      Physical execution requires a separately qualified
                      connection and operator authorization. It is not available
                      here.
                    </p>
                  </div>
                </>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
