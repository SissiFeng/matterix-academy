import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  ArrowLeft,
  ArrowUp,
  ArrowDown,
  Check,
  ChevronRight,
  Monitor,
  Pause,
  Play,
  Plus,
  RotateCcw,
  SkipForward,
  Trash2,
  X,
  AlertTriangle,
  CheckCircle2,
  Circle,
  Pipette,
} from "lucide-react";
import { api, ApiError, json } from "./api";
import type { Action, Experiment, Session } from "./types";
import s from "./App.module.css";
import { useDialog } from "./useDialog";
import { LABWARE, LABELS, format, LabwareDrawing, Deck } from "./deck";

export default function DilutionWorkspace({
  session,
  onChange,
  onBack,
  onError,
  registerLeaveGuard,
}: {
  session: Session;
  onChange: (s: Session) => void;
  onBack: () => void;
  onError: (message: string) => void;
  registerLeaveGuard: (guard: (() => boolean) | null) => void;
}) {
  const [draft, setDraft] = useState<Experiment>(
    structuredClone(session.experiment),
  );
  const [tab, setTab] = useState<"bench" | "method" | "results">("bench");
  const [selected, setSelected] = useState<string | null>("tips");
  const [busy, setBusy] = useState(false);
  const [auto, setAuto] = useState(false);
  const [viewer, setViewer] = useState(false);
  const closeViewer = useCallback(() => setViewer(false), []);
  useDialog(viewer, closeViewer);
  const stateRef = useRef(session);
  stateRef.current = session;
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const dirty = JSON.stringify(draft) !== JSON.stringify(session.experiment);
  useEffect(() => {
    registerLeaveGuard(
      () => !dirty || window.confirm("Leave without saving your changes?"),
    );
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => {
      registerLeaveGuard(null);
      window.removeEventListener("beforeunload", beforeUnload);
    };
  }, [dirty, registerLeaveGuard]);
  const editable = session.status === "draft";
  const accept = useCallback(
    (next: Session) => {
      if (!mounted.current) return;
      onChange(next);
      setDraft(structuredClone(next.experiment));
    },
    [onChange],
  );
  const handleError = useCallback(
    async (error: unknown) => {
      if (!mounted.current) return;
      setAuto(false);
      onError(error instanceof Error ? error.message : "Something went wrong.");
      if (error instanceof ApiError && error.status === 409) {
        try {
          accept(await api<Session>(`/sessions/${stateRef.current.id}`));
        } catch {
          /* Original error remains visible. */
        }
      }
    },
    [accept, onError],
  );
  const persist = async () => {
    if (!dirty) return session;
    const next = await api<Session>(
      `/sessions/${session.id}`,
      json({ version: session.version, experiment: draft }, "PUT"),
    );
    accept(next);
    return next;
  };
  const perform = async (command: string) => {
    setBusy(true);
    try {
      let current = session;
      if (command === "start" || command === "step") current = await persist();
      if (command === "step") {
        if (current.status === "draft" || current.status === "paused")
          current = await api<Session>(
            `/sessions/${current.id}/${current.status === "draft" ? "start" : "resume"}`,
            json({ version: current.version }),
          );
        current = await api<Session>(
          `/sessions/${current.id}/advance`,
          json({ version: current.version }),
        );
        if (current.status === "running")
          current = await api<Session>(
            `/sessions/${current.id}/pause`,
            json({ version: current.version }),
          );
        accept(current);
      } else {
        const next = await api<Session>(
          `/sessions/${current.id}/${command}`,
          json({ version: current.version }),
        );
        accept(next);
        setAuto(command === "start" || command === "resume");
      }
    } catch (error) {
      await handleError(error);
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    if (!auto || busy || session.status !== "running") return;
    const timer = window.setTimeout(async () => {
      setBusy(true);
      try {
        const next = await api<Session>(
          `/sessions/${session.id}/advance`,
          json({ version: session.version }),
        );
        accept(next);
        if (next.status === "completed" || next.status === "faulted") {
          setAuto(false);
          setTab("results");
        }
      } catch (error) {
        await handleError(error);
      } finally {
        setBusy(false);
      }
    }, 650);
    return () => window.clearTimeout(timer);
  }, [
    auto,
    busy,
    session.id,
    session.version,
    session.status,
    accept,
    handleError,
  ]);
  const place = (slot: string, asset?: string) => {
    const target = asset || selected;
    if (!editable || !target || !LABWARE[target]) return;
    if (target === "waste" || slot === "D3") {
      onError(
        "The Flex waste chute is fixed at D3; choose another slot for movable labware.",
      );
      return;
    }
    const layout = { ...draft.layout };
    const previous = layout[target];
    const occupant = Object.keys(layout).find((key) => layout[key] === slot);
    if (occupant) layout[occupant] = previous;
    layout[target] = slot;
    setDraft({ ...draft, layout });
    setSelected(target);
  };
  const editAction = (index: number, patch: Partial<Action>) =>
    setDraft({
      ...draft,
      actions: draft.actions.map((a, i) =>
        i === index ? { ...a, ...patch } : a,
      ),
    });
  const move = (index: number, delta: number) => {
    const actions = [...draft.actions];
    [actions[index], actions[index + delta]] = [
      actions[index + delta],
      actions[index],
    ];
    setDraft({ ...draft, actions });
  };
  const lastError = session.events.find((e) => e.level === "error");
  const guardBack = () => {
    onBack();
  };
  return (
    <div className={s.workspace}>
      <div className={s.workspaceHeading}>
        <button className={s.textButton} onClick={guardBack}>
          <ArrowLeft size={16} /> My workspace
        </button>
        <span className={s.modelBadge}>
          <span className={s.noteDot} /> Teaching model · simulation only
        </span>
      </div>
      <div className={s.experimentHeading}>
        <div>
          {editable ? (
            <input
              className={s.titleInput}
              aria-label="Experiment title"
              maxLength={80}
              value={draft.title}
              onChange={(e) => setDraft({ ...draft, title: e.target.value })}
            />
          ) : (
            <h1>{draft.title}</h1>
          )}
        </div>
        <span className={`${s.status} ${s[session.status]}`}>
          {session.status === "faulted" ? "Needs a rethink" : session.status}
        </span>
      </div>
      <div className={s.labToolbar}>
        <div className={s.tabs}>
          {(["bench", "method", "results"] as const).map((t, i) => (
            <button
              key={t}
              className={tab === t ? s.activeTab : ""}
              onClick={() => setTab(t)}
            >
              <span>0{i + 1}</span>
              {t === "bench"
                ? "Lab bench"
                : t === "method"
                  ? "Your method"
                  : "Observations"}
            </button>
          ))}
        </div>
        <span className={s.saveState}>
          {dirty ? (
            "Unsaved changes"
          ) : (
            <>
              <Check size={13} /> Saved
            </>
          )}
        </span>
      </div>
      <div className={s.labBody}>
        <section className={s.mainPanel}>
          {tab === "bench" ? (
            <>
              <div className={s.panelTop}>
                <div>
                  <strong>A place for everything.</strong>
                  <p>
                    Select a piece of labware, then choose a slot. Occupied
                    slots swap. The waste chute is fixed at D3.
                  </p>
                  {draft.layout.waste !== "D3" && (
                    <button
                      className={s.secondary}
                      disabled={!editable}
                      onClick={() => {
                        const layout = { ...draft.layout };
                        const occupant = Object.keys(layout).find(
                          (key) => layout[key] === "D3",
                        );
                        if (occupant) layout[occupant] = layout.waste;
                        layout.waste = "D3";
                        setDraft({ ...draft, layout });
                      }}
                    >
                      Correct legacy waste chute position
                    </button>
                  )}
                </div>
                <button className={s.secondary} onClick={() => setViewer(true)}>
                  <Monitor size={15} /> Matterix 3D
                </button>
              </div>
              <Deck
                layout={draft.layout}
                selected={selected}
                onPlace={place}
                locked={!editable}
              />
              <div className={s.labwareTray}>
                {Object.entries(LABWARE).map(([id, item]) => (
                  <button
                    key={id}
                    draggable={editable && id !== "waste"}
                    onDragStart={(e) =>
                      e.dataTransfer.setData("text/plain", id)
                    }
                    className={selected === id ? s.selectedAsset : ""}
                    disabled={!editable || id === "waste"}
                    onClick={() => setSelected(id)}
                  >
                    <LabwareDrawing kind={id} />
                    <span>
                      <strong>{item.name}</strong>
                      <small>
                        {draft.layout[id]} · {item.detail}
                      </small>
                    </span>
                  </button>
                ))}
              </div>
              <div className={s.initialLiquids}>
                <label>
                  Starting stock <span>µL</span>
                  <input
                    type="number"
                    min="0"
                    max="1500"
                    aria-label="Starting stock volume"
                    disabled={!editable}
                    value={draft.source_volume}
                    onChange={(e) =>
                      setDraft({
                        ...draft,
                        source_volume: Number(e.target.value),
                      })
                    }
                  />
                </label>
                <label>
                  Diluent in each well <span>µL</span>
                  <input
                    type="number"
                    min="0"
                    max="1500"
                    aria-label="Diluent volume"
                    disabled={!editable}
                    value={draft.diluent_volume}
                    onChange={(e) =>
                      setDraft({
                        ...draft,
                        diluent_volume: Number(e.target.value),
                      })
                    }
                  />
                </label>
                <p>
                  Stock concentration: 100%.
                  <br />
                  The teaching model assumes instant, ideal mixing.
                </p>
              </div>
            </>
          ) : tab === "method" ? (
            <>
              <div className={s.panelTop}>
                <div>
                  <strong>Small steps. A complete experiment.</strong>
                  <p>
                    Change the order, volume or destination. Then see what
                    happens.
                  </p>
                </div>
                <span className={s.caption}>
                  {draft.actions.length} / 64 steps
                </span>
              </div>
              <div className={s.actionList}>
                {draft.actions.map((action, index) => (
                  <div
                    key={index}
                    className={`${s.actionRow} ${index === session.cursor && session.status !== "draft" ? s.currentAction : ""}`}
                  >
                    <span className={s.actionNumber}>
                      {index < session.cursor ? (
                        <Check size={15} />
                      ) : (
                        String(index + 1).padStart(2, "0")
                      )}
                    </span>
                    <select
                      aria-label={`Step ${index + 1} action`}
                      value={action.kind}
                      disabled={!editable}
                      onChange={(e) =>
                        editAction(index, {
                          kind: e.target.value as Action["kind"],
                        })
                      }
                    >
                      {Object.entries(LABELS).map(([v, label]) => (
                        <option key={v} value={v}>
                          {label}
                        </option>
                      ))}
                    </select>
                    {["aspirate", "dispense"].includes(action.kind) ? (
                      <>
                        <select
                          aria-label={`Step ${index + 1} well`}
                          value={action.well}
                          disabled={!editable}
                          onChange={(e) =>
                            editAction(index, {
                              well: e.target.value as Action["well"],
                            })
                          }
                        >
                          {["stock", "A1", "A2", "A3"].map((w) => (
                            <option key={w} value={w}>
                              {w === "stock" ? "Stock" : `Well ${w}`}
                            </option>
                          ))}
                        </select>
                        <label className={s.volumeInput}>
                          <input
                            type="number"
                            aria-label={`Step ${index + 1} volume`}
                            min="1"
                            max="1000"
                            value={action.volume}
                            disabled={!editable}
                            onChange={(e) =>
                              editAction(index, {
                                volume: Number(e.target.value),
                              })
                            }
                          />
                          <span>µL</span>
                        </label>
                      </>
                    ) : (
                      <span className={s.actionDescription}>
                        {action.kind === "pickup"
                          ? "Attach a fresh 300 µL tip"
                          : "Release the current tip into waste"}
                      </span>
                    )}
                    <div className={s.actionTools}>
                      <button
                        aria-label={`Move step ${index + 1} up`}
                        disabled={!editable || index === 0}
                        onClick={() => move(index, -1)}
                      >
                        <ArrowUp size={15} />
                      </button>
                      <button
                        aria-label={`Move step ${index + 1} down`}
                        disabled={
                          !editable || index === draft.actions.length - 1
                        }
                        onClick={() => move(index, 1)}
                      >
                        <ArrowDown size={15} />
                      </button>
                      <button
                        aria-label={`Delete step ${index + 1}`}
                        disabled={!editable || draft.actions.length === 1}
                        onClick={() =>
                          setDraft({
                            ...draft,
                            actions: draft.actions.filter(
                              (_, i) => i !== index,
                            ),
                          })
                        }
                      >
                        <Trash2 size={15} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
              <button
                className={s.addStep}
                disabled={!editable || draft.actions.length >= 64}
                onClick={() =>
                  setDraft({
                    ...draft,
                    actions: [
                      ...draft.actions,
                      { kind: "pickup", well: "stock", volume: 100 },
                    ],
                  })
                }
              >
                <Plus size={17} /> Add a step
              </button>
            </>
          ) : (
            <>
              <div className={s.panelTop}>
                <div>
                  <strong>
                    {session.status === "completed"
                      ? session.assessment?.passed
                        ? "You reached the learning goal."
                        : "The sequence finished. What would you change?"
                      : lastError
                        ? "A useful place to pause."
                        : "Watch your experiment take shape."}
                  </strong>
                  <p>
                    Observations from this teaching model, saved step by step.
                  </p>
                </div>
              </div>
              {lastError && (
                <div className={s.errorCard}>
                  <AlertTriangle size={23} />
                  <div>
                    <strong>
                      Step {lastError.step}: {lastError.message}
                    </strong>
                    <p>{lastError.hint}</p>
                    <span>
                      Reset the experiment, adjust your method and try again.
                    </span>
                  </div>
                </div>
              )}
              {session.assessment && (
                <div className={s.assessment}>
                  {session.assessment.checks.map((c) => (
                    <div key={c.label}>
                      {c.passed ? (
                        <CheckCircle2 size={18} />
                      ) : (
                        <Circle size={18} />
                      )}
                      <span>{c.label}</span>
                      <strong>{c.passed ? "Reached" : "Try again"}</strong>
                    </div>
                  ))}
                </div>
              )}
              <div className={s.observationTable}>
                <div>
                  <span>CONTAINER</span>
                  <span>VOLUME</span>
                  <span>CONCENTRATION</span>
                </div>
                {Object.entries(session.state.wells).map(([name, well]) => (
                  <div key={name}>
                    <strong>
                      {name === "stock" ? "Stock solution" : `Well ${name}`}
                    </strong>
                    <span>{format(well.volume)} µL</span>
                    <span>
                      {well.volume ? format(well.solute / well.volume) : "0"}%
                    </span>
                  </div>
                ))}
              </div>
              <div className={s.eventLog}>
                <h3>Experiment timeline</h3>
                {!session.events.length && (
                  <p>
                    No actions yet. Run your method to start collecting
                    observations.
                  </p>
                )}
                {session.events.map((event) => (
                  <div key={`${event.step}-${event.code}`}>
                    <span
                      className={
                        event.level === "error" ? s.errorDot : s.eventDot
                      }
                    />
                    <span>STEP {String(event.step).padStart(2, "0")}</span>
                    <p>{event.message}</p>
                  </div>
                ))}
              </div>
              {session.attempts.length > 0 && (
                <div className={s.attempts}>
                  <h3>Earlier attempts</h3>
                  {session.attempts.map((attempt, i) => (
                    <p key={i}>
                      Attempt {i + 1} · {attempt.steps} steps ·{" "}
                      {attempt.assessment?.passed
                        ? "Goal reached"
                        : attempt.status}
                      {attempt.last_event?.level === "error"
                        ? ` — ${attempt.last_event.message}`
                        : ""}
                    </p>
                  ))}
                </div>
              )}
            </>
          )}
        </section>
        <aside className={s.runPanel}>
          <div className={s.runPanelTitle}>
            <Pipette size={18} />
            <span>Experiment companion</span>
          </div>
          <div className={s.runProgress}>
            <span>
              {String(session.cursor).padStart(2, "0")}
              <small> / {String(draft.actions.length).padStart(2, "0")}</small>
            </span>
            <p>steps completed</p>
            <div>
              <i
                style={{
                  width: `${(session.cursor / draft.actions.length) * 100}%`,
                }}
              />
            </div>
          </div>
          <div className={s.nextStep}>
            <span>NEXT ACTION</span>
            <strong>
              {session.cursor < draft.actions.length
                ? LABELS[draft.actions[session.cursor].kind]
                : "Sequence complete"}
            </strong>
            <p>
              {session.status === "draft"
                ? "Your method is ready to explore."
                : session.status === "faulted"
                  ? "Review the observation, then reset to try a different approach."
                  : session.status === "completed"
                    ? "Check your concentrations against the learning goal."
                    : session.status === "running" && !auto
                      ? "Auto-run stopped when you left the page. Continue or advance one step."
                      : "You can pause and inspect the state at any time."}
            </p>
          </div>
          <div className={s.runControls}>
            {session.status === "running" && auto ? (
              <button
                className={s.primary}
                disabled={busy}
                onClick={() => perform("pause")}
              >
                <Pause size={16} /> Pause experiment
              </button>
            ) : session.status === "running" ? (
              <button
                className={s.primary}
                disabled={busy}
                onClick={() => setAuto(true)}
              >
                <Play size={16} /> Continue experiment
              </button>
            ) : ["draft", "paused"].includes(session.status) ? (
              <button
                className={s.primary}
                disabled={busy}
                onClick={() =>
                  perform(session.status === "draft" ? "start" : "resume")
                }
              >
                <Play size={16} />{" "}
                {session.status === "paused"
                  ? "Resume experiment"
                  : "Run experiment"}
              </button>
            ) : (
              <button
                className={s.primary}
                disabled={busy}
                onClick={() => {
                  perform("reset");
                  setTab("method");
                }}
              >
                <RotateCcw size={16} /> Reset & try again
              </button>
            )}
            <button
              className={s.secondary}
              disabled={
                busy ||
                auto ||
                !["draft", "paused", "running"].includes(session.status)
              }
              onClick={() => perform("step")}
            >
              <SkipForward size={16} /> One step at a time
            </button>
            <div>
              <button
                className={s.textButton}
                disabled={busy || !dirty}
                onClick={async () => {
                  setBusy(true);
                  try {
                    await persist();
                  } catch (e) {
                    await handleError(e);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Save changes
              </button>
              <button
                className={s.textButton}
                disabled={busy || session.status === "draft"}
                onClick={() => perform("reset")}
              >
                <RotateCcw size={13} /> Reset
              </button>
            </div>
          </div>
          <div className={s.liveState}>
            <div>
              <span>Tip attached</span>
              <strong>{session.state.pipette.tip ? "Yes" : "No"}</strong>
            </div>
            <div>
              <span>Liquid in tip</span>
              <strong>{format(session.state.pipette.volume)} µL</strong>
            </div>
            <div>
              <span>Fresh tips used</span>
              <strong>{session.state.tips_used} / 96</strong>
            </div>
          </div>
          <div className={s.goalNote}>
            <span>YOUR LEARNING GOAL</span>
            <p>Create a 1:2 dilution series.</p>
            <div>
              <strong>50%</strong>
              <ChevronRight size={13} />
              <strong>25%</strong>
              <ChevronRight size={13} />
              <strong>12.5%</strong>
            </div>
            <small>A1 → A2 → A3 · use a fresh tip for each transfer</small>
          </div>
        </aside>
      </div>
      {viewer && (
        <div className={s.modalBackdrop} onClick={() => setViewer(false)}>
          <section
            className={s.modal}
            role="dialog"
            aria-modal="true"
            aria-labelledby="viewer-title"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className={s.closeButton}
              aria-label="Close viewer information"
              onClick={() => setViewer(false)}
            >
              <X size={20} />
            </button>
            <Monitor size={35} />
            <h2 id="viewer-title">Your 3D lab is not connected yet.</h2>
            <p>
              The Ubuntu Matterix gateway must be connected and verified before
              a live 3D session can open. Your current experiment runs in the
              teaching model.
            </p>
            <p>
              There is no live robot motion or collision simulation in this
              preview.
            </p>
            <button className={s.primary} onClick={() => setViewer(false)}>
              Back to my experiment
              <ArrowRight size={16} />
            </button>
          </section>
        </div>
      )}
    </div>
  );
}
