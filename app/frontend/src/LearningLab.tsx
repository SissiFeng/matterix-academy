import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleHelp,
  FlaskConical,
  Monitor,
  Pause,
  Play,
  RotateCcw,
  SkipForward,
  WifiOff,
} from "lucide-react";
import { api, json } from "./api";
import type { LearningProgress, Session } from "./types";
import {
  EMPTY_LEARNING,
  EQUIPMENT,
  PHASES,
  PREPARATION,
  firstTransfer,
  stepExplanation,
} from "./learningContent";
import type { EquipmentId } from "./learningContent";
import FlexDiagram from "./FlexDiagram";
import s from "./LearningLab.module.css";

const number = (value: number) =>
  Number(value.toFixed(2)).toLocaleString("en-US");
export function FirstLessonCard({
  onStart,
  resume,
}: {
  onStart: () => void;
  resume: boolean;
}) {
  return (
    <section className={s.lessonCard}>
      <div>
        <span className={s.eyebrow}>
          START HERE / BUILD ON YOUR MANUAL LAB SKILLS
        </span>
        <h2>
          Meet your first
          <br />
          <em>automated pipetting workstation.</em>
        </h2>
        <p>
          From finding tips and wells to explaining a 100 µL transfer.
          <br />
          Explore the equipment, predict the result, then try it yourself.
        </p>
        <button className={s.primary} onClick={onStart}>
          {resume ? "Continue my Flex lesson" : "Start learning Flex"}
          <ArrowRight size={18} />
        </button>
        <small>5 learning stages · Guided practice · No coding required</small>
      </div>
      <div className={s.lessonIndex}>
        {PHASES.map((p, i) => (
          <div key={p.id}>
            <span>0{i + 1}</span>
            <div>
              <strong>{p.title}</strong>
              <small>{p.detail}</small>
            </div>
            <ChevronRight size={15} />
          </div>
        ))}
      </div>
    </section>
  );
}

function RemoteView() {
  const [status, setStatus] = useState<{
    state: string;
    message: string;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const active = useRef(true);
  const check = useCallback(async () => {
    setBusy(true);
    try {
      const next = await api<{ state: string; message: string }>(
        "/remote/status",
      );
      if (active.current) setStatus(next);
    } catch {
      if (active.current)
        setStatus({
          state: "unreachable",
          message:
            "Unable to check the connection right now. Please try again.",
        });
    } finally {
      if (active.current) setBusy(false);
    }
  }, []);
  useEffect(() => {
    active.current = true;
    check();
    return () => {
      active.current = false;
    };
  }, [check]);
  return (
    <div className={s.remote}>
      <Monitor size={38} />
      <span className={s.eyebrow}>REMOTE LAB / UBUNTU</span>
      <h3>Live 3D simulation is not connected yet</h3>
      <p>{status?.message ?? "Checking the remote lab connection…"}</p>
      <div className={s.connectionPath}>
        <span>Your browser</span>
        <ChevronRight size={14} />
        <span>Academy</span>
        <ChevronRight size={14} />
        <span>Ubuntu simulation</span>
      </div>
      <p>
        Once connected and verified, this view will show Matterix live. For now,
        use the independent teaching model to explore equipment, predict results
        and practice the action sequence.
      </p>
      <button className={s.secondary} onClick={check} disabled={busy}>
        <RotateCcw size={15} />
        {busy ? "Checking…" : "Check connection again"}
      </button>
      <small>
        Students do not need an Ubuntu account. Your lab administrator
        configures the connection.
      </small>
    </div>
  );
}

export default function LearningLab({
  session,
  onChange,
  onBack,
  onError,
  registerLeaveGuard,
}: {
  session: Session;
  onChange: (next: Session) => void;
  onBack: () => void;
  onError: (message: string) => void;
  registerLeaveGuard: (guard: (() => boolean) | null) => void;
}) {
  const learning = session.learning ?? EMPTY_LEARNING;
  const [selected, setSelected] = useState<EquipmentId>("pipette");
  const [view, setView] = useState<"diagram" | "remote">("diagram");
  const [busy, setBusy] = useState(false);
  const [auto, setAuto] = useState(false);
  const [prediction, setPrediction] = useState({
    source: learning.prediction?.source.toString() ?? "",
    tip: learning.prediction?.tip.toString() ?? "",
    target: learning.prediction?.target.toString() ?? "",
  });
  const [predictionMessage, setPredictionMessage] = useState("");
  const [predictionDirty, setPredictionDirty] = useState(false);
  const lock = useRef(false);
  const mounted = useRef(true);
  const current = useRef(session);
  current.current = session;
  const volume = session.experiment.transfer_volume ?? 100;
  const phase = learning.phase;
  const phaseIndex = PHASES.findIndex((p) => p.id === phase);
  const explanation = stepExplanation(
    session.cursor,
    volume,
    session.experiment.source_volume,
  );
  const evidence = EQUIPMENT[selected];
  const orientDone =
    session.readiness?.checks.find((c) => c.id === "orientation")?.passed ??
    false;
  const preparationDone =
    session.readiness?.checks.find((c) => c.id === "preparation")?.passed ??
    false;
  const predictionDone =
    session.readiness?.checks.find((c) => c.id === "prediction")?.passed ??
    false;
  const derivedDone = [
    orientDone,
    preparationDone,
    predictionDone,
    session.status === "completed",
    session.lesson_outcome?.practice_completed &&
      session.lesson_outcome?.understanding_demonstrated,
  ];
  const completed = derivedDone[4];
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    registerLeaveGuard(
      () =>
        !predictionDirty ||
        window.confirm("Your prediction is not saved. Leave this lesson?"),
    );
    const warn = (e: BeforeUnloadEvent) => {
      if (predictionDirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", warn);
    return () => {
      registerLeaveGuard(null);
      window.removeEventListener("beforeunload", warn);
    };
  }, [predictionDirty, registerLeaveGuard]);
  const accept = useCallback(
    (next: Session) => {
      if (mounted.current) {
        current.current = next;
        onChange(next);
      }
    },
    [onChange],
  );
  const task = useCallback(
    async (action: () => Promise<Session>) => {
      if (lock.current || !mounted.current) return;
      lock.current = true;
      setBusy(true);
      try {
        const next = await action();
        accept(next);
        return next;
      } catch (e) {
        if (mounted.current) {
          setAuto(false);
          onError(
            e instanceof Error
              ? e.message
              : "The operation did not complete. Please try again.",
          );
          try {
            // A multi-request action may have saved its first step before failing.
            accept(await api<Session>(`/sessions/${current.current.id}`));
          } catch {
            /* Keep the original failure visible; never replay the mutation. */
          }
        }
      } finally {
        lock.current = false;
        if (mounted.current) setBusy(false);
      }
    },
    [accept, onError],
  );
  const saveProgress = (patch: Partial<LearningProgress>) =>
    task(() =>
      api<Session>(
        `/sessions/${current.current.id}/learning`,
        json(
          {
            version: current.current.version,
            learning: { ...current.current.learning, ...patch },
          },
          "PUT",
        ),
      ),
    );
  const changePhase = async (next: LearningProgress["phase"]) => {
    if (
      predictionDirty &&
      !window.confirm("Your prediction is not saved. Switch stages?")
    )
      return;
    const saved = await saveProgress({ phase: next });
    if (saved) {
      setPrediction({
        source: saved.learning?.prediction?.source.toString() ?? "",
        tip: saved.learning?.prediction?.tip.toString() ?? "",
        target: saved.learning?.prediction?.target.toString() ?? "",
      });
      setPredictionDirty(false);
      setPredictionMessage("");
      setView("diagram");
    }
  };
  const select = async (id: EquipmentId) => {
    setSelected(id);
    if (phase === "orient" && !learning.visited.includes(id) && !busy)
      await saveProgress({ visited: [...learning.visited, id] });
  };
  const control = (command: string) =>
    api<Session>(
      `/sessions/${current.current.id}/${command}`,
      json({ version: current.current.version }),
    );
  const perform = async (single: boolean) => {
    const next = await task(async () => {
      let run = current.current;
      if (run.status === "draft" || run.status === "paused") {
        run = await control(run.status === "draft" ? "start" : "resume");
        current.current = run;
      }
      if (single) {
        run = await control("advance");
        current.current = run;
        if (run.status === "running") run = await control("pause");
      }
      return run;
    });
    if (next && !single) setAuto(true);
  };
  useEffect(() => {
    if (!auto || busy || session.status !== "running") return;
    const timer = window.setTimeout(
      () =>
        task(async () => {
          const next = await api<Session>(
            `/sessions/${current.current.id}/advance`,
            json({ version: current.current.version }),
          );
          if (next.status !== "running" && mounted.current) setAuto(false);
          return next;
        }),
      1200,
    );
    return () => window.clearTimeout(timer);
  }, [auto, busy, session.version, session.status, task]);
  useEffect(() => {
    if (phase === "run" && session.cursor < 4)
      setSelected(
        stepExplanation(
          session.cursor,
          volume,
          session.experiment.source_volume,
        ).object as EquipmentId,
      );
  }, [phase, session.cursor, volume, session.experiment.source_volume]);
  const checkPrediction = async () => {
    if (
      Object.values(prediction).some(
        (v) => !v.trim() || !Number.isFinite(Number(v)) || Number(v) < 0,
      )
    ) {
      setPredictionMessage(
        "Enter a non-negative volume for all three locations, then check your prediction.",
      );
      return;
    }
    const saved = await saveProgress({
      prediction: {
        source: Number(prediction.source),
        tip: Number(prediction.tip),
        target: Number(prediction.target),
      },
    });
    if (saved) {
      setPredictionDirty(false);
      setPredictionMessage(
        saved.readiness?.checks.find((check) => check.id === "prediction")
          ?.passed
          ? "Correct. Aspiration draws liquid into the tip; the target well is still empty."
          : "Think again: aspiration moves liquid from the source into the tip. Nothing has been dispensed yet. Check all three volumes.",
      );
    }
  };
  const restart = async (nextVolume: number) => {
    if (
      !window.confirm(
        "Save this attempt and start again from the initial state?",
      )
    )
      return;
    setAuto(false);
    const next = await task(async () => {
      const reset = await control("reset");
      current.current = reset;
      return api<Session>(
        `/sessions/${reset.id}`,
        json(
          {
            version: reset.version,
            experiment: {
              ...firstTransfer(nextVolume),
              layout: reset.experiment.layout,
            },
          },
          "PUT",
        ),
      );
    });
    if (next) {
      setPrediction({ source: "", tip: "", target: "" });
      setPredictionDirty(false);
      setPredictionMessage("");
    }
  };
  return (
    <div className={s.workspace}>
      <div className={s.breadcrumb}>
        <button onClick={onBack}>
          <ArrowLeft size={15} /> Back to courses
        </button>
        <span>FLEX / LESSON ONE</span>
        <span className={s.source}>
          Teaching model · Not a remote simulation
        </span>
      </div>
      <header className={s.heading}>
        <div>
          <span className={s.eyebrow}>FROM MANUAL PIPETTING TO AUTOMATION</span>
          <h1>
            Move {volume} µL <em>to the right place.</em>
          </h1>
          <p>
            Explore the equipment, predict what will change and observe each
            action. Your progress is saved with your experiment.
          </p>
        </div>
        <div className={s.progressRing}>
          <strong>
            {derivedDone.filter(Boolean).length}
            <small>/ 5</small>
          </strong>
          <span>Learning stages</span>
        </div>
      </header>
      <div className={s.learningGrid}>
        <nav className={s.phaseNav} aria-label="Lesson stages">
          <span className={s.eyebrow}>YOUR LEARNING PATH</span>
          {PHASES.map((p, i) => (
            <button
              key={p.id}
              aria-current={phase === p.id ? "step" : undefined}
              className={phase === p.id ? s.currentPhase : ""}
              onClick={() => changePhase(p.id)}
              disabled={busy || session.status === "running"}
            >
              <span className={s.phaseNumber}>
                {derivedDone[i] ? (
                  <Check size={15} />
                ) : (
                  String(i + 1).padStart(2, "0")
                )}
              </span>
              <span>
                <strong>{p.title}</strong>
                <small>{p.detail}</small>
              </span>
            </button>
          ))}
          <div className={s.pathNote}>
            <BookOpen size={19} />
            <p>
              You already know how to pipette.
              <br />
              Now, tell the robot
              <br />
              what to do, one step at a time.
            </p>
          </div>
          <a
            href="https://docs.opentrons.com/flex/"
            target="_blank"
            rel="noreferrer"
          >
            Opentrons official manual ↗
          </a>
        </nav>
        <section
          className={s.stage}
          aria-label="Equipment and experiment workspace"
        >
          <div className={s.viewTabs}>
            <button
              aria-pressed={view === "diagram"}
              onClick={() => setView("diagram")}
            >
              Equipment tour <span>Teaching diagram</span>
            </button>
            <button
              aria-pressed={view === "remote"}
              onClick={() => setView("remote")}
            >
              <Monitor size={15} /> Remote 3D <WifiOff size={13} />
            </button>
          </div>
          {view === "remote" ? (
            <RemoteView />
          ) : (
            <>
              <FlexDiagram
                session={session}
                selected={selected}
                onSelect={select}
              />
              <div className={s.objectButtons}>
                {(Object.keys(EQUIPMENT) as EquipmentId[]).map((id) => (
                  <button
                    key={id}
                    disabled={busy}
                    aria-pressed={selected === id}
                    onClick={() => select(id)}
                  >
                    {learning.visited.includes(id) ? (
                      <Check size={13} />
                    ) : (
                      <span className={s.objectDot} />
                    )}{" "}
                    {EQUIPMENT[id].name}
                  </button>
                ))}
              </div>
            </>
          )}
          <div className={s.selection}>
            <span>Selected object</span>
            <strong>{evidence.name}</strong>
            <span>
              {selected === "pipette"
                ? "Robot-mounted pipette"
                : `Slot ${session.experiment.layout[selected]}${selected === "plate" ? " → Target plate → Well A1" : ""}`}
            </span>
          </div>
          {phase === "prepare" && (
            <div className={s.deckEditor}>
              <h3>Place your labware</h3>
              <p>
                Selecting an occupied slot swaps the labware. D3 is reserved for
                the fixed waste chute. This layout exercise does not simulate
                reachability.
              </p>
              <div>
                {(["stock", "plate", "tips"] as const).map((id) => (
                  <label key={id}>
                    {EQUIPMENT[id].name}
                    <select
                      aria-label={`${EQUIPMENT[id].name} slot`}
                      disabled={busy || session.status !== "draft"}
                      value={session.experiment.layout[id]}
                      onChange={(e) => {
                        const slot = e.target.value;
                        const layout = { ...session.experiment.layout };
                        const occupant = Object.keys(layout).find(
                          (key) => layout[key] === slot,
                        );
                        if (occupant) layout[occupant] = layout[id];
                        layout[id] = slot;
                        task(() =>
                          api<Session>(
                            `/sessions/${session.id}`,
                            json(
                              {
                                version: session.version,
                                experiment: { ...session.experiment, layout },
                              },
                              "PUT",
                            ),
                          ),
                        );
                      }}
                    >
                      {[..."ABCD"]
                        .flatMap((row) =>
                          [1, 2, 3].map((col) => `${row}${col}`),
                        )
                        .filter((slot) => slot !== "D3")
                        .map((slot) => (
                          <option key={slot}>{slot}</option>
                        ))}
                    </select>
                  </label>
                ))}
              </div>
            </div>
          )}
          <div className={s.stateHeading}>
            <strong>Liquid volumes</strong>
            <span>Source: teaching model calculations</span>
          </div>
          <div className={s.liquidStates}>
            {[
              {
                name: "Source container",
                value: session.state.wells.stock.volume,
                detail: `Slot ${session.experiment.layout.stock}`,
              },
              {
                name: "Inside the tip",
                value: session.state.pipette.volume,
                detail: session.state.pipette.tip
                  ? "Tip attached"
                  : "No tip attached",
              },
              {
                name: "Target well A1",
                value: session.state.wells.A1.volume,
                detail: `Slot ${session.experiment.layout.plate} → Plate`,
              },
            ].map((item) => (
              <div key={item.name}>
                <span>{item.name}</span>
                <strong>
                  {number(item.value)}
                  <small> µL</small>
                </strong>
                <small>{item.detail}</small>
              </div>
            ))}
          </div>
          <div className={s.timeline}>
            {session.experiment.actions.map((action, i) => (
              <div
                key={i}
                className={
                  i < session.cursor
                    ? s.executed
                    : i === session.cursor
                      ? s.nextAction
                      : ""
                }
              >
                <span>{i < session.cursor ? <Check size={12} /> : i + 1}</span>
                {
                  {
                    pickup: "Pick up tip",
                    aspirate: "Aspirate",
                    dispense: "Dispense",
                    drop: "Discard tip",
                  }[action.kind]
                }
                <small>
                  {i < session.cursor
                    ? "Complete"
                    : i === session.cursor
                      ? "Next action"
                      : "Pending"}
                </small>
              </div>
            ))}
          </div>
        </section>
        <aside className={s.companion}>
          <span className={s.eyebrow}>
            0{phaseIndex + 1} / {PHASES[phaseIndex].title}
          </span>
          {phase === "orient" && (
            <>
              <h2>{evidence.name}</h2>
              <p>{evidence.purpose}</p>
              <div className={s.comparison}>
                <span>{evidence.manual}</span>
                <ArrowRight size={15} />
                <strong>{evidence.robot}</strong>
              </div>
              <div className={s.note}>
                <CircleHelp size={16} />
                <p>{evidence.notice}</p>
              </div>
              <small>
                Explored {new Set(learning.visited).size} / 5 objects. Select an
                object to learn more.
              </small>
              <fieldset>
                <legend>
                  In “well A1 of the plate in slot D2”, what does A1 identify?
                </legend>
                {(
                  [
                    ["well", "A well in the plate"],
                    ["slot", "Another deck slot"],
                  ] as const
                ).map(([value, label]) => (
                  <label key={value}>
                    <input
                      type="radio"
                      name="location"
                      checked={learning.location_answer === value}
                      disabled={busy}
                      onChange={() => saveProgress({ location_answer: value })}
                    />
                    {label}
                  </label>
                ))}
              </fieldset>
              {learning.location_answer === "slot" && (
                <p className={s.feedback}>
                  Slots hold labware; wells receive liquid. Here, A1 is a well
                  in the plate.
                </p>
              )}
              <button
                className={s.primary}
                disabled={busy || !orientDone}
                onClick={() => changePhase("prepare")}
              >
                Prepare the experiment <ArrowRight size={16} />
              </button>
            </>
          )}
          {phase === "prepare" && (
            <>
              <h2>
                Before you begin,
                <br />
                check your setup.
              </h2>
              <p>
                Start with {number(session.experiment.source_volume)} µL in the
                source. Transfer {volume} µL into empty well A1.
              </p>
              <div className={s.checklist}>
                {PREPARATION.map((check) => (
                  <label key={check.id}>
                    <input
                      type="checkbox"
                      disabled={busy || session.status !== "draft"}
                      checked={learning.checks.includes(check.id)}
                      onChange={() =>
                        saveProgress({
                          checks: learning.checks.includes(check.id)
                            ? learning.checks.filter((c) => c !== check.id)
                            : [...learning.checks, check.id],
                        })
                      }
                    />
                    <span>
                      <strong>{check.title}</strong>
                      <small>{check.detail}</small>
                    </span>
                  </label>
                ))}
              </div>
              <div className={s.note}>
                <CircleHelp size={16} />
                <p>
                  This is a virtual preparation exercise. A physical Flex still
                  requires a real Labware Position Check and hands-on training.
                </p>
              </div>
              <button
                className={s.primary}
                disabled={busy || !orientDone || !preparationDone}
                onClick={() => changePhase("predict")}
              >
                Predict the volumes <ArrowRight size={16} />
              </button>
            </>
          )}
          {phase === "predict" && (
            <>
              <h2>
                After aspiration,
                <br />
                where is the liquid?
              </h2>
              <p>
                The source contains {number(session.experiment.source_volume)}{" "}
                µL. The tip and target well are empty. Aspirate {volume} µL,
                without dispensing yet.
              </p>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  checkPrediction();
                }}
                className={s.predictionForm}
              >
                {(
                  [
                    { key: "source", label: "Source volume remaining" },
                    { key: "tip", label: "Volume in the tip" },
                    { key: "target", label: "Volume in target well A1" },
                  ] as const
                ).map((field) => (
                  <label key={field.key}>
                    {field.label}
                    <div>
                      <input
                        type="number"
                        min="0"
                        max={field.key === "tip" ? 300 : 1500}
                        step="any"
                        required
                        value={prediction[field.key]}
                        disabled={busy || session.status !== "draft"}
                        onChange={(e) => {
                          setPrediction({
                            ...prediction,
                            [field.key]: e.target.value,
                          });
                          setPredictionDirty(true);
                          setPredictionMessage("");
                        }}
                      />
                      <span>µL</span>
                    </div>
                  </label>
                ))}
                <button
                  className={s.secondary}
                  disabled={busy || session.status !== "draft"}
                >
                  Check my prediction
                </button>
              </form>
              <p role="status" className={s.feedback}>
                {predictionMessage ||
                  (predictionDone
                    ? "Your correct prediction is saved. Compare it with the model as you run."
                    : "Hint: the total volume across all three locations should stay the same.")}
              </p>
              <button
                className={s.primary}
                disabled={busy || !session.readiness?.ready || predictionDirty}
                onClick={() => changePhase("run")}
              >
                Start practicing <ArrowRight size={16} />
              </button>
            </>
          )}
          {phase === "run" && (
            <>
              <h2>
                {session.status === "completed"
                  ? "Transfer complete. Now explain it."
                  : explanation.title}
              </h2>
              <span className={s.english}>
                {session.status === "completed"
                  ? "Practice complete"
                  : explanation.english}
              </span>
              {session.status !== "completed" ? (
                <>
                  <h3>Why this action matters</h3>
                  <p>{explanation.why}</p>
                  <h3>Before this action</h3>
                  <p>{explanation.before}</p>
                  <div className={s.expected}>
                    <span>What to expect</span>
                    <strong>{explanation.expect}</strong>
                  </div>
                </>
              ) : (
                <>
                  <p>
                    Compare the source, tip and target with your prediction.
                    Then explain how the liquid reached its destination.
                  </p>
                  <div className={s.assessment}>
                    {session.assessment?.checks.map((c) => (
                      <p key={c.label}>
                        <CheckCircle2 size={15} />
                        {c.label}
                      </p>
                    ))}
                  </div>
                </>
              )}
              {!session.readiness?.ready && (
                <div className={s.note}>
                  <CircleHelp size={16} />
                  <div>
                    <p>Complete these checks before running:</p>
                    {session.readiness?.checks
                      .filter((c) => !c.passed)
                      .map((c) => (
                        <p key={c.id}>{c.label}</p>
                      ))}
                  </div>
                </div>
              )}
              {session.status === "faulted" && (
                <div role="alert" className={s.note}>
                  <p>
                    {session.events.at(-1)?.message}
                    <br />
                    {session.events.at(-1)?.hint}
                  </p>
                </div>
              )}
              {session.status === "completed" ? (
                <button
                  className={s.primary}
                  disabled={busy}
                  onClick={() => changePhase("reflect")}
                >
                  Explain the result and try again <ArrowRight size={16} />
                </button>
              ) : session.status === "faulted" ? (
                <button
                  className={s.primary}
                  disabled={busy}
                  onClick={() => restart(volume)}
                >
                  Retry from the initial state
                </button>
              ) : (
                <div className={s.runControls}>
                  <button
                    className={s.primary}
                    disabled={busy || !session.readiness?.ready || auto}
                    onClick={() => perform(true)}
                  >
                    <SkipForward size={16} />
                    {busy ? "Running…" : "Run next step"}
                  </button>
                  {auto || session.status === "running" ? (
                    <button
                      className={s.secondary}
                      disabled={busy}
                      onClick={() => {
                        setAuto(false);
                        task(() => control("pause"));
                      }}
                    >
                      <Pause size={15} /> Pause practice
                    </button>
                  ) : (
                    <button
                      className={s.secondary}
                      disabled={busy || !session.readiness?.ready}
                      onClick={() => perform(false)}
                    >
                      <Play size={15} /> Run continuously
                    </button>
                  )}
                </div>
              )}
              <small>
                Single-step pauses after each action. The teaching model stops
                advancing when you leave this page.
              </small>
              <details>
                <summary>View action history · {session.events.length}</summary>
                {session.events.length ? (
                  session.events.map((event, i) => (
                    <p key={i}>
                      {event.step}. {event.message}
                    </p>
                  ))
                ) : (
                  <p>No actions have run yet.</p>
                )}
              </details>
            </>
          )}
          {phase === "reflect" && (
            <>
              <h2>
                {completed
                  ? "You can explain your first transfer."
                  : "Reflect on what happened."}
              </h2>
              <p>
                After aspiration and before dispensing, where has the liquid
                moved?
              </p>
              <fieldset>
                <legend>Choose the explanation that matches the action</legend>
                {(
                  [
                    [
                      "source_to_tip",
                      "From the source into the tip; the target is still empty",
                    ],
                    [
                      "source_to_target",
                      "Directly from the source into the target well",
                    ],
                    ["target_to_tip", "From the target well back into the tip"],
                  ] as const
                ).map(([value, label]) => (
                  <label key={value}>
                    <input
                      type="radio"
                      name="reflection"
                      disabled={busy || session.status !== "completed"}
                      checked={learning.reflection === value}
                      onChange={() => saveProgress({ reflection: value })}
                    />
                    {label}
                  </label>
                ))}
              </fieldset>
              {session.status !== "completed" ? (
                <p className={s.feedback}>
                  Complete a transfer first, then use the results to answer.
                </p>
              ) : learning.reflection &&
                learning.reflection !== "source_to_tip" ? (
                <p className={s.feedback}>
                  The target is still empty after aspiration. Dispensing moves
                  the liquid from the tip into the target.
                </p>
              ) : completed ? (
                <div className={s.success}>
                  <CheckCircle2 size={22} />
                  <strong>Practice and understanding complete</strong>
                  <p>
                    This result comes from the teaching model. It is not
                    certification to operate a physical robot.
                  </p>
                </div>
              ) : null}
              <h3>Change one condition and try again</h3>
              <p>
                Change the volume to {volume === 100 ? 50 : 100} µL. Check the
                setup and predict again. Can you complete it without relying on
                your previous answers?
              </p>
              <button
                className={s.primary}
                disabled={busy || session.status !== "completed"}
                onClick={() => restart(volume === 100 ? 50 : 100)}
              >
                <RotateCcw size={16} /> Try a {volume === 100 ? 50 : 100} µL
                transfer
              </button>
              <small>
                This experiment keeps the last 10 attempt summaries. Saved
                attempts: {session.attempts.length}.
              </small>
              <div className={s.note}>
                <FlaskConical size={17} />
                <p>
                  Next: serial dilution, which adds diluent, mixing and multiple
                  target wells. The current dilution exercise assumes ideal
                  mixing.
                </p>
              </div>
            </>
          )}
        </aside>
      </div>
      <div className={s.lessonFooter}>
        <span>
          <CheckCircle2 size={14} />{" "}
          {busy
            ? "Saving or running…"
            : predictionDirty
              ? "Prediction not saved"
              : "Learning progress saved"}
        </span>
        <span>Lesson v1 · Explore freely, complete the checks, then run</span>
      </div>
    </div>
  );
}
