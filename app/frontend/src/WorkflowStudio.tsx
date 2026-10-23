import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import {
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  Check,
  CheckCircle2,
  Copy,
  Droplets,
  FlaskConical,
  Layers3,
  Pause,
  Pipette,
  Play,
  Plus,
  RotateCcw,
  Save,
  SkipForward,
  Trash2,
  TriangleAlert,
} from "lucide-react";
import { api, ApiError, json } from "./api";
import type { Action, Experiment, Session } from "./types";
import {
  ACTION_HINTS,
  ACTION_LABELS,
  INSTRUMENT_NAMES,
  makeStudioExperiment,
  STARTERS,
} from "./studioContent";
import type { Instrument, Starter } from "./studioContent";
import s from "./WorkflowStudio.module.css";

const format = (value: number) => Number(value.toFixed(2)).toLocaleString();
const assetNames: Record<string, string> = {
  stock: "Stock solution",
  plate: "Destination wells",
  tips: "Tip rack",
  waste: "Fixed waste",
};
const slots = (instrument: Instrument) =>
  instrument === "flex"
    ? "ABCD".split("").flatMap((row) => [1, 2, 3].map((col) => `${row}${col}`))
    : [10, 11, 12, 7, 8, 9, 4, 5, 6, 1, 2, 3].map(String);

function LiquidVessel({
  volume,
  capacity = 1500,
}: {
  volume: number;
  capacity?: number;
}) {
  return (
    <span className={s.vessel} aria-hidden="true">
      <i style={{ height: `${Math.min(100, (volume / capacity) * 100)}%` }} />
    </span>
  );
}

export default function WorkflowStudio({
  session,
  onChange,
  onBack,
  onError,
  registerLeaveGuard,
}: {
  session: Session;
  onChange: (session: Session) => void;
  onBack: () => void;
  onError: (message: string) => void;
  registerLeaveGuard: (guard: (() => boolean) | null) => void;
}) {
  const [draft, setDraft] = useState<Experiment>(() =>
    structuredClone(session.experiment),
  );
  const [busy, setBusy] = useState(false);
  const [auto, setAuto] = useState(false);
  const [selectedAsset, setSelectedAsset] = useState("tips");
  const [starter, setStarter] = useState<Starter>("transfer");
  const mounted = useRef(true);
  const runControls = useRef<HTMLElement>(null);
  const blocks = useRef<HTMLElement>(null);
  const pending = useRef(false);
  const current = useRef(session);
  current.current = session;
  const instrument = draft.instrument ?? "flex";
  const editable = session.status === "draft" && !busy;
  const dirty = JSON.stringify(draft) !== JSON.stringify(session.experiment);
  const empty = draft.actions.length === 0;
  const fault = session.events.find((event) => event.level === "error");
  const activeStep =
    session.status === "draft" ? null : draft.actions[session.cursor];
  const activeAsset = activeStep
    ? activeStep.kind === "pickup"
      ? "tips"
      : activeStep.kind === "drop"
        ? "waste"
        : activeStep.well === "stock"
          ? "stock"
          : "plate"
    : null;
  const wells =
    session.status === "draft"
      ? {
          stock: {
            volume: draft.source_volume,
            solute: draft.source_volume * 100,
          },
          ...Object.fromEntries(
            ["A1", "A2", "A3"].map((well) => [
              well,
              { volume: draft.diluent_volume, solute: 0 },
            ]),
          ),
        }
      : session.state.wells;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    setDraft(structuredClone(session.experiment));
    setAuto(false);
    // Each session owns its draft; API responses are accepted separately below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session.id]);
  useEffect(() => {
    registerLeaveGuard(
      () => !dirty || window.confirm("Leave without saving your workflow?"),
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
  const isActive = (id: string) => mounted.current && current.current.id === id;
  const accept = useCallback(
    (next: Session) => {
      if (
        !mounted.current ||
        next.id !== current.current.id ||
        next.version < current.current.version
      )
        return;
      current.current = next;
      onChange(next);
      setDraft(structuredClone(next.experiment));
    },
    [onChange],
  );
  const handleError = useCallback(
    async (error: unknown, id: string) => {
      if (!mounted.current || current.current.id !== id) return;
      setAuto(false);
      onError(
        error instanceof Error
          ? error.message
          : "The workflow could not be updated.",
      );
      if (error instanceof ApiError && error.status === 409) {
        try {
          accept(await api<Session>(`/sessions/${id}`));
        } catch {
          /* Keep the original error visible. */
        }
      }
    },
    [accept, onError],
  );
  const persist = async () => {
    const base = current.current;
    if (JSON.stringify(draft) === JSON.stringify(base.experiment)) return base;
    const next = await api<Session>(
      `/sessions/${base.id}`,
      json({ version: base.version, experiment: draft }, "PUT"),
    );
    accept(next);
    return next;
  };
  const perform = async (
    command: "save" | "start" | "pause" | "resume" | "reset" | "step",
  ) => {
    if (pending.current) return;
    pending.current = true;
    const id = current.current.id;
    setBusy(true);
    if (command === "pause" || command === "reset") setAuto(false);
    try {
      let next = current.current;
      if (command === "save" || command === "start" || command === "step")
        next = await persist();
      if (!isActive(id) || command === "save") return;
      if (command === "step") {
        if (next.status === "draft" || next.status === "paused") {
          next = await api<Session>(
            `/sessions/${id}/${next.status === "draft" ? "start" : "resume"}`,
            json({ version: next.version }),
          );
          if (!isActive(id)) return;
        }
        next = await api<Session>(
          `/sessions/${id}/advance`,
          json({ version: next.version }),
        );
        if (!isActive(id)) return;
        if (next.status === "running")
          next = await api<Session>(
            `/sessions/${id}/pause`,
            json({ version: next.version }),
          );
      } else {
        next = await api<Session>(
          `/sessions/${id}/${command}`,
          json({ version: next.version }),
        );
      }
      if (!isActive(id)) return;
      accept(next);
      setAuto(command === "start" || command === "resume");
    } catch (error) {
      await handleError(error, id);
    } finally {
      pending.current = false;
      if (isActive(id)) setBusy(false);
    }
  };
  useEffect(() => {
    if (!auto || busy || session.status !== "running") return;
    const timer = window.setTimeout(async () => {
      if (pending.current) return;
      pending.current = true;
      setBusy(true);
      const id = session.id;
      try {
        const next = await api<Session>(
          `/sessions/${id}/advance`,
          json({ version: session.version }),
        );
        if (!mounted.current || current.current.id !== id) return;
        accept(next);
        if (next.status !== "running") setAuto(false);
      } catch (error) {
        await handleError(error, id);
      } finally {
        pending.current = false;
        if (mounted.current && current.current.id === id) setBusy(false);
      }
    }, 600);
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

  const editAction = (index: number, patch: Partial<Action>) =>
    setDraft((value) => ({
      ...value,
      actions: value.actions.map((action, i) =>
        i === index ? { ...action, ...patch } : action,
      ),
    }));
  const addAction = (kind: Action["kind"]) =>
    setDraft((value) => ({
      ...value,
      actions: [
        ...value.actions,
        { kind, well: kind === "dispense" ? "A1" : "stock", volume: 100 },
      ],
    }));
  const move = (index: number, delta: number) =>
    setDraft((value) => {
      const actions = [...value.actions];
      [actions[index], actions[index + delta]] = [
        actions[index + delta],
        actions[index],
      ];
      return { ...value, actions };
    });
  const place = (slot: string) => {
    if (!editable || slot === draft.layout.waste) return;
    setDraft((value) => {
      const layout = { ...value.layout };
      const occupant = Object.keys(layout).find(
        (asset) => layout[asset] === slot,
      );
      if (occupant) layout[occupant] = layout[selectedAsset];
      layout[selectedAsset] = slot;
      return { ...value, layout };
    });
  };
  const loadStarter = () => {
    if (!window.confirm("Replace this draft with the selected starter?"))
      return;
    setDraft(makeStudioExperiment(instrument, starter));
  };
  const progress = empty ? 0 : (session.cursor / draft.actions.length) * 100;

  return (
    <div
      className={s.studio}
      data-testid="workflow-studio"
      data-instrument={instrument}
    >
      <div className={s.topline}>
        <button className={s.textButton} onClick={onBack}>
          <ArrowLeft size={16} /> Instrument introductions
        </button>
        <span className={s.evidence}>
          <i /> Synthetic teaching model
        </span>
      </div>
      <header className={s.heading}>
        <div>
          <p className={s.eyebrow}>
            {INSTRUMENT_NAMES[instrument]} / CREATE & EXPLORE
          </p>
          <h1>
            Workflow studio<span>.</span>
          </h1>
          <p>Make a plan. Move some liquid. See where your idea takes you.</p>
        </div>
        <div className={s.headerActions}>
          <span className={s.saved} role="status">
            {busy ? (
              "Updating…"
            ) : dirty ? (
              "Unsaved changes"
            ) : (
              <>
                <Check size={14} /> Saved
              </>
            )}
          </span>
          <button
            className={s.secondary}
            disabled={!editable || !dirty}
            onClick={() => perform("save")}
          >
            <Save size={16} /> Save workflow
          </button>
        </div>
      </header>
      <div className={s.mobileJumps} role="group" aria-label="Studio sections">
        <button
          className={s.secondary}
          onClick={() => {
            blocks.current?.scrollIntoView({ block: "start" });
            blocks.current?.focus({ preventScroll: true });
          }}
        >
          Edit blocks <Layers3 size={15} />
        </button>
        <button
          className={s.secondary}
          onClick={() => {
            runControls.current?.scrollIntoView({ block: "start" });
            runControls.current?.focus({ preventScroll: true });
          }}
        >
          Preview & run <Play size={15} />
        </button>
      </div>
      <div className={s.nameRow}>
        <label>
          WORKFLOW NAME
          <input
            aria-label="Workflow name"
            maxLength={80}
            value={draft.title}
            disabled={!editable}
            onChange={(event) =>
              setDraft({ ...draft, title: event.target.value })
            }
          />
        </label>
        <span
          className={`${s.status} ${session.status === "faulted" ? s.faultStatus : ""}`}
        >
          {session.status === "faulted"
            ? "Needs a rethink"
            : session.status === "completed"
              ? "Sequence completed"
              : session.status}
        </span>
      </div>
      <div className={s.columns}>
        <section
          className={s.plan}
          aria-label="Workflow blocks"
          ref={blocks}
          tabIndex={-1}
        >
          <div className={s.sectionHeading}>
            <div>
              <span className={s.sectionNumber}>01</span>
              <h2>Build your workflow</h2>
            </div>
            <span>{draft.actions.length} / 64 blocks</span>
          </div>
          <div className={s.starterRow}>
            <label>
              Start from
              <select
                aria-label="Workflow starter"
                value={starter}
                disabled={!editable}
                onChange={(event) => setStarter(event.target.value as Starter)}
              >
                {Object.entries(STARTERS).map(([key, value]) => (
                  <option key={key} value={key}>
                    {value.title}
                  </option>
                ))}
              </select>
            </label>
            <button
              className={s.textButton}
              disabled={!editable}
              onClick={loadStarter}
            >
              Load starter
            </button>
          </div>
          <p className={s.subtle}>
            Add a block, then change its volume or destination. Use the arrows
            to change the order.
          </p>
          <div
            className={s.palette}
            role="group"
            aria-label="Add a workflow block"
          >
            {(Object.keys(ACTION_LABELS) as Action["kind"][]).map((kind) => (
              <button
                className={s[kind]}
                key={kind}
                disabled={!editable || draft.actions.length >= 64}
                onClick={() => addAction(kind)}
                aria-label={`Add ${ACTION_LABELS[kind].toLowerCase()} block`}
              >
                <Plus size={14} /> {ACTION_LABELS[kind]}
              </button>
            ))}
          </div>
          <ol className={s.blockList}>
            {draft.actions.map((action, index) => (
              <li
                key={index}
                className={`${s.block} ${s[action.kind]} ${session.status !== "draft" && index === session.cursor ? s.currentBlock : ""} ${index < session.cursor ? s.doneBlock : ""}`}
                data-testid={`workflow-step-${index + 1}`}
                aria-current={
                  session.status !== "draft" && index === session.cursor
                    ? "step"
                    : undefined
                }
              >
                <div className={s.blockTop}>
                  <span className={s.blockNumber}>
                    {index < session.cursor ? (
                      <Check size={14} />
                    ) : (
                      String(index + 1).padStart(2, "0")
                    )}
                  </span>
                  <select
                    aria-label={`Step ${index + 1} action`}
                    value={action.kind}
                    disabled={!editable}
                    onChange={(event) =>
                      editAction(index, {
                        kind: event.target.value as Action["kind"],
                      })
                    }
                  >
                    {Object.entries(ACTION_LABELS).map(([kind, label]) => (
                      <option value={kind} key={kind}>
                        {label}
                      </option>
                    ))}
                  </select>
                  <div className={s.blockTools}>
                    <button
                      aria-label={`Move step ${index + 1} up`}
                      disabled={!editable || index === 0}
                      onClick={() => move(index, -1)}
                    >
                      <ArrowUp size={14} />
                    </button>
                    <button
                      aria-label={`Move step ${index + 1} down`}
                      disabled={!editable || index === draft.actions.length - 1}
                      onClick={() => move(index, 1)}
                    >
                      <ArrowDown size={14} />
                    </button>
                    <button
                      aria-label={`Duplicate step ${index + 1}`}
                      disabled={!editable || draft.actions.length >= 64}
                      onClick={() =>
                        setDraft({
                          ...draft,
                          actions: [
                            ...draft.actions.slice(0, index + 1),
                            { ...action },
                            ...draft.actions.slice(index + 1),
                          ],
                        })
                      }
                    >
                      <Copy size={14} />
                    </button>
                    <button
                      aria-label={`Delete step ${index + 1}`}
                      disabled={!editable}
                      onClick={() =>
                        setDraft({
                          ...draft,
                          actions: draft.actions.filter((_, i) => i !== index),
                        })
                      }
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
                {action.kind === "aspirate" || action.kind === "dispense" ? (
                  <div className={s.blockParameters}>
                    <label>
                      {action.kind === "aspirate" ? "FROM" : "INTO"}
                      <select
                        aria-label={`Step ${index + 1} well`}
                        value={action.well}
                        disabled={!editable}
                        onChange={(event) =>
                          editAction(index, {
                            well: event.target.value as Action["well"],
                          })
                        }
                      >
                        {["stock", "A1", "A2", "A3"].map((well) => (
                          <option key={well} value={well}>
                            {well === "stock"
                              ? "Stock solution"
                              : `Well ${well}`}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      VOLUME
                      <span className={s.volumeInput}>
                        <input
                          type="number"
                          aria-label={`Step ${index + 1} volume`}
                          min={1}
                          max={1000}
                          value={action.volume}
                          disabled={!editable}
                          onChange={(event) =>
                            editAction(index, {
                              volume: Number(event.target.value),
                            })
                          }
                        />
                        <span>µL</span>
                      </span>
                    </label>
                  </div>
                ) : (
                  <p className={s.blockHint}>{ACTION_HINTS[action.kind]}</p>
                )}
              </li>
            ))}
          </ol>
          {empty && (
            <div className={s.empty}>
              <Layers3 size={30} />
              <h3>Your idea starts here.</h3>
              <p>
                Add a pick-up block, draw liquid, choose a destination, then
                discard the tip. Or try a starter above.
              </p>
              <button
                className={s.secondary}
                disabled={!editable}
                onClick={() => addAction("pickup")}
              >
                <Plus size={16} /> Add your first block
              </button>
            </div>
          )}
          {!empty && (
            <p className={s.planEnd}>
              <span /> End of workflow
            </p>
          )}
        </section>
        <aside className={s.preview}>
          <section
            className={s.runPanel}
            aria-label="Teaching simulation controls"
            ref={runControls}
            tabIndex={-1}
          >
            <div className={s.runTop}>
              <span>
                <Pipette size={17} /> TEACHING SIMULATION
              </span>
              <strong>
                {session.cursor} / {draft.actions.length}
              </strong>
            </div>
            <div
              className={s.progress}
              role="progressbar"
              aria-label="Workflow progress"
              aria-valuemin={0}
              aria-valuemax={draft.actions.length || 1}
              aria-valuenow={session.cursor}
            >
              <i style={{ width: `${progress}%` }} />
            </div>
            <p className={s.runMessage}>
              {session.status === "draft"
                ? empty
                  ? "Add at least one block to run your idea."
                  : "Your design is ready to explore. Changes save when you run."
                : session.status === "completed"
                  ? "Sequence completed. Explore the model observations below."
                  : session.status === "faulted"
                    ? "The model paused at a useful learning moment. Review the hint below."
                    : `Next: ${activeStep ? ACTION_LABELS[activeStep.kind] : "Finish"}. ${session.status === "running" && !auto ? "Continue when you are ready." : "You can inspect one step at a time."}`}
            </p>
            {session.status === "running" && auto ? (
              <button
                className={s.primary}
                disabled={busy}
                onClick={() => perform("pause")}
              >
                <Pause size={18} /> Pause simulation
              </button>
            ) : session.status === "running" ? (
              <button
                className={s.primary}
                disabled={busy}
                onClick={() => setAuto(true)}
              >
                <Play size={18} /> Continue simulation
              </button>
            ) : session.status === "draft" || session.status === "paused" ? (
              <button
                className={s.primary}
                disabled={busy || empty}
                onClick={() =>
                  perform(session.status === "draft" ? "start" : "resume")
                }
              >
                <Play size={18} />{" "}
                {session.status === "paused"
                  ? "Resume simulation"
                  : "Run teaching simulation"}
              </button>
            ) : (
              <button
                className={s.primary}
                disabled={busy}
                onClick={() => perform("reset")}
              >
                <RotateCcw size={18} /> Reset & edit
              </button>
            )}
            <div className={s.runSecondary}>
              <button
                className={s.textButton}
                disabled={
                  busy ||
                  auto ||
                  empty ||
                  !["draft", "paused", "running"].includes(session.status)
                }
                onClick={() => perform("step")}
              >
                <SkipForward size={15} /> Advance one step
              </button>
              <button
                className={s.textButton}
                disabled={busy || session.status === "draft"}
                onClick={() => perform("reset")}
              >
                <RotateCcw size={14} /> Reset run
              </button>
            </div>
            <div className={s.pipetteState}>
              <span>
                Tip {session.state.pipette.tip ? "attached" : "not attached"}
              </span>
              <strong>{format(session.state.pipette.volume)} µL in tip</strong>
              <span>{session.state.tips_used} tips used</span>
            </div>
          </section>
          <section
            className={s.deckPanel}
            aria-label={`${INSTRUMENT_NAMES[instrument]} teaching deck`}
          >
            <div className={s.sectionHeading}>
              <div>
                <span className={s.sectionNumber}>02</span>
                <h2>Your teaching deck</h2>
              </div>
              <span>{instrument === "flex" ? "FLEX" : "OT-2"}</span>
            </div>
            <div className={s.deckCaption}>
              <span>BACK OF INSTRUMENT</span>
              <span>TOP VIEW · SCHEMATIC</span>
            </div>
            <div className={s.deck} data-testid="studio-deck">
              {slots(instrument).map((slot) => {
                const asset = Object.keys(draft.layout).find(
                  (key) => draft.layout[key] === slot,
                );
                return (
                  <button
                    key={slot}
                    className={`${s.slot} ${asset ? s.occupied : ""} ${asset === selectedAsset && editable ? s.selectedSlot : ""} ${asset && activeAsset === asset ? s.activeSlot : ""}`}
                    aria-label={`Slot ${slot}: ${asset ? assetNames[asset] : "empty"}`}
                    disabled={!editable || slot === draft.layout.waste}
                    onClick={() => place(slot)}
                  >
                    <span className={s.slotId}>{slot}</span>
                    {asset === "stock" ? (
                      <LiquidVessel volume={wells.stock.volume} />
                    ) : asset === "plate" ? (
                      <span className={s.miniWells}>
                        {["A1", "A2", "A3"].map((well) => (
                          <i
                            key={well}
                            className={
                              activeStep?.well === well ? s.activeWell : ""
                            }
                            style={
                              {
                                "--fill": `${Math.min(100, wells[well].volume / 15)}%`,
                              } as CSSProperties
                            }
                          >
                            <span>{well}</span>
                          </i>
                        ))}
                      </span>
                    ) : asset === "tips" ? (
                      <span className={s.tipRack}>
                        {Array.from({ length: 15 }, (_, i) => (
                          <i key={i} />
                        ))}
                      </span>
                    ) : asset === "waste" ? (
                      <Trash2 className={s.waste} size={27} />
                    ) : (
                      <Plus className={s.emptySlot} size={13} />
                    )}
                    {asset && (
                      <span className={s.assetName}>{assetNames[asset]}</span>
                    )}
                  </button>
                );
              })}
            </div>
            <div className={s.deckFront}>FRONT / YOU</div>
            <div className={s.placement}>
              <label>
                Move labware
                <select
                  aria-label="Labware to move"
                  value={selectedAsset}
                  disabled={!editable}
                  onChange={(event) => setSelectedAsset(event.target.value)}
                >
                  {["tips", "stock", "plate"].map((asset) => (
                    <option key={asset} value={asset}>
                      {assetNames[asset]} · {draft.layout[asset]}
                    </option>
                  ))}
                </select>
              </label>
              <p>
                Select a piece, then a deck slot. Occupied slots swap. Waste
                stays at {draft.layout.waste}.
              </p>
            </div>
            <details className={s.setup}>
              <summary>
                <FlaskConical size={15} /> Starting liquids{" "}
                <span>{format(draft.source_volume)} µL stock</span>
              </summary>
              <div className={s.initialVolumes}>
                <label>
                  Stock solution (µL)
                  <input
                    type="number"
                    aria-label="Starting stock volume"
                    min={0}
                    max={1500}
                    value={draft.source_volume}
                    disabled={!editable}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        source_volume: Number(event.target.value),
                      })
                    }
                  />
                </label>
                <label>
                  Diluent in each well (µL)
                  <input
                    type="number"
                    aria-label="Starting diluent volume"
                    min={0}
                    max={1500}
                    value={draft.diluent_volume}
                    disabled={!editable}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        diluent_volume: Number(event.target.value),
                      })
                    }
                  />
                </label>
              </div>
              <p>
                Stock is a 100% reference tracer. Each destination starts with
                the same amount of diluent.
              </p>
            </details>
          </section>
          <section className={s.liveLiquids} aria-label="Container volumes">
            <div className={s.sectionHeading}>
              <h2>
                <Droplets size={16} /> Liquid snapshot
              </h2>
              <span>
                {session.status === "draft"
                  ? "STARTING PREVIEW"
                  : "SAVED MODEL STATE"}
              </span>
            </div>
            <div className={s.liquidGrid}>
              {Object.entries(wells).map(([name, well]) => (
                <div key={name} data-testid={`liquid-${name}`}>
                  <span>{name === "stock" ? "Stock" : name}</span>
                  <strong>
                    {format(well.volume)}
                    <small> µL</small>
                  </strong>
                  <span>
                    {well.volume ? format(well.solute / well.volume) : "0"}%
                    stock
                  </span>
                </div>
              ))}
            </div>
          </section>
        </aside>
      </div>
      <section className={s.observations} aria-label="Model observations">
        <div className={s.sectionHeading}>
          <div>
            <span className={s.sectionNumber}>03</span>
            <h2>Observe. Change. Try again.</h2>
          </div>
          <span>SYNTHETIC RESULTS</span>
        </div>
        {fault && (
          <div className={s.fault} role="status">
            <TriangleAlert size={23} />
            <div>
              <h3>
                Step {fault.step}: {fault.message}
              </h3>
              <p>{fault.hint}</p>
              <p>
                Choose “Reset & edit”, adjust your blocks and run again. Your
                earlier attempt stays saved.
              </p>
            </div>
          </div>
        )}
        {session.assessment && (
          <div className={s.checks}>
            <div>
              <h3>Teaching model checks</h3>
              <p>
                These checks describe your sequence and liquid bookkeeping. Your
                design has no prescribed dilution target.
              </p>
            </div>
            <ul>
              {session.assessment.checks.map((check) => (
                <li key={check.label}>
                  {check.passed ? (
                    <CheckCircle2 size={17} />
                  ) : (
                    <TriangleAlert size={17} />
                  )}
                  <span>{check.label}</span>
                  <strong>{check.passed ? "Passed" : "Review"}</strong>
                </li>
              ))}
            </ul>
          </div>
        )}
        {!session.events.length && (
          <p className={s.observationEmpty}>
            Run your workflow to see each transfer, model check and learning
            moment here.
          </p>
        )}
        {!!session.events.length && (
          <details className={s.timeline} open={session.status === "faulted"}>
            <summary>
              Step timeline <span>{session.events.length} observations</span>
            </summary>
            <ol>
              {session.events.map((event) => (
                <li key={`${event.step}-${event.code}`}>
                  <span>{String(event.step).padStart(2, "0")}</span>
                  <p>{event.message}</p>
                  {event.level === "error" ? (
                    <TriangleAlert size={15} />
                  ) : (
                    <Check size={15} />
                  )}
                </li>
              ))}
            </ol>
          </details>
        )}
        {!!session.attempts.length && (
          <details className={s.timeline}>
            <summary>
              Earlier attempts <span>{session.attempts.length} saved</span>
            </summary>
            <ol>
              {session.attempts.map((attempt, index) => (
                <li key={index}>
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  <p>
                    Attempt {index + 1} · {attempt.steps} steps ·{" "}
                    {attempt.status}
                    {attempt.last_event?.level === "error"
                      ? ` — ${attempt.last_event.message}`
                      : ""}
                  </p>
                </li>
              ))}
            </ol>
          </details>
        )}
      </section>
      <p className={s.boundary}>
        A simplified 300 µL pipette, ideal mixing and fresh-tip rules on both
        instrument layouts. Deck placement is schematic. Results are synthetic;
        this studio does not run a robot, validate a protocol or simulate
        collision physics.
      </p>
    </div>
  );
}
