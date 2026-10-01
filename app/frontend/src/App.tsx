import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  ArrowLeft,
  ArrowUp,
  ArrowDown,
  Beaker,
  BookOpen,
  Check,
  ChevronRight,
  CircleHelp,
  Clock3,
  FlaskConical,
  History,
  LayoutGrid,
  LogOut,
  Maximize2,
  Monitor,
  Pause,
  Play,
  Plus,
  RotateCcw,
  ShieldCheck,
  SkipForward,
  Trash2,
  X,
  AlertTriangle,
  CheckCircle2,
  Circle,
  Pipette,
  Layers3,
  Compass,
  Store,
  GitBranch,
} from "lucide-react";
import { api, ApiError, configureAuth, json, signIn, signOut } from "./api";
import type {
  Action,
  Config,
  Course,
  Experiment,
  Profile,
  Session,
} from "./types";
import s from "./App.module.css";
import { useDialog } from "./useDialog";
import LearningLab, { FirstLessonCard } from "./LearningLab";
import { firstTransfer } from "./learningContent";
import {
  DiscoveryInvitation,
  DiscoveryStudio,
  WorkflowMarketplace,
} from "./Discovery";
import { workflows, type Workflow } from "./discoveryContent";
import ConnectorExplorer from "./ConnectorExplorer";

const LABWARE: Record<string, { name: string; detail: string }> = {
  stock: { name: "Stock solution", detail: "1,500 µL vial" },
  plate: { name: "Destination wells", detail: "A1 · A2 · A3" },
  tips: { name: "Tip rack", detail: "96 × 300 µL" },
  waste: { name: "Waste chute", detail: "Used tips" },
};
const SLOTS = "ABCD"
  .split("")
  .flatMap((row) => [1, 2, 3].map((col) => `${row}${col}`));
const LABELS = {
  pickup: "Pick up tip",
  aspirate: "Aspirate",
  dispense: "Dispense",
  drop: "Discard tip",
};
const format = (n: number) => Number(n.toFixed(2)).toLocaleString();

function Brand({ small = false }: { small?: boolean }) {
  return (
    <div className={`${s.brand} ${small ? s.smallBrand : ""}`}>
      <span className={s.brandMark}>
        <span />
        <span />
        <span />
        <span />
      </span>
      <span>
        Lab<span className={s.brandSub}>Onboarding</span>
      </span>
    </div>
  );
}

function LabwareDrawing({ kind }: { kind: string }) {
  if (kind === "tips")
    return (
      <div className={s.tipRack}>
        {Array.from({ length: 24 }, (_, i) => (
          <i key={i} />
        ))}
      </div>
    );
  if (kind === "plate")
    return (
      <div className={s.wellPlate}>
        {Array.from({ length: 6 }, (_, i) => (
          <i key={i} />
        ))}
      </div>
    );
  if (kind === "stock")
    return (
      <div className={s.vial}>
        <span />
        <i />
      </div>
    );
  return (
    <div className={s.chute}>
      <span />
    </div>
  );
}

function Deck({
  layout,
  selected,
  onPlace,
  locked = false,
  large = false,
}: {
  layout: Record<string, string>;
  selected?: string | null;
  onPlace?: (slot: string, asset?: string) => void;
  locked?: boolean;
  large?: boolean;
}) {
  return (
    <div className={`${s.deck} ${large ? s.largeDeck : ""}`}>
      <div className={s.deckRail}>
        <span>FLEX</span>
        <i />
        <span>DECK / TOP VIEW</span>
      </div>
      <div className={s.deckSlots}>
        {SLOTS.map((slot) => {
          const asset = Object.keys(layout).find((key) => layout[key] === slot);
          return (
            <button
              key={slot}
              className={`${s.slot} ${asset ? s.occupied : ""} ${selected && asset === selected ? s.selectedSlot : ""}`}
              aria-label={`${slot}${asset ? `: ${LABWARE[asset].name}` : ": empty"}${selected ? " — place selected labware" : ""}`}
              disabled={locked || !onPlace}
              onClick={() => onPlace?.(slot)}
              onDragOver={(e) => {
                if (!locked) e.preventDefault();
              }}
              onDrop={(e) => {
                e.preventDefault();
                if (!locked)
                  onPlace?.(slot, e.dataTransfer.getData("text/plain"));
              }}
            >
              <span className={s.slotLabel}>{slot}</span>
              {asset && (
                <>
                  <LabwareDrawing kind={asset} />
                  <span className={s.assetLabel}>{LABWARE[asset].name}</span>
                </>
              )}
            </button>
          );
        })}
      </div>
      <div className={s.deckFoot}>
        <span>OPENTRONS FLEX</span>
        <span>SCHEMATIC PREVIEW</span>
      </div>
    </div>
  );
}

function Welcome({
  config,
  onEnter,
  busy,
}: {
  config: Config;
  onEnter: (name: string) => void;
  busy: boolean;
}) {
  const [name, setName] = useState("");
  return (
    <main className={s.welcome}>
      <header>
        <Brand />
        <span className={s.headerNote}>
          <ShieldCheck size={15} /> A safe space to learn
        </span>
      </header>
      <div className={s.welcomeGrid}>
        <section className={s.welcomeCopy}>
          <div className={s.eyebrow}>THE LAB IS YOURS.</div>
          <h1>
            Good experiments
            <br />
            start with
            <br />
            <em>a little curiosity.</em>
          </h1>
          <p>
            Build a workflow. Make a mistake. Try again.
            <br />
            Build skills for simulation and supervised lab practice.
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              onEnter(name.trim() || "Learner");
            }}
          >
            {config.auth === "local" && (
              <label className={s.nameInput}>
                What should we call you?
                <input
                  autoComplete="given-name"
                  maxLength={60}
                  placeholder="Your first name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </label>
            )}
            <button
              className={s.primary}
              disabled={busy || config.auth === "disabled"}
            >
              {busy
                ? "Opening your workspace…"
                : config.auth === "cognito"
                  ? config.self_signup_email_domains?.length
                    ? "Sign in or create an account"
                    : "Sign in to Lab Onboarding"
                  : "Enter the learning lab"}
              <ArrowRight size={18} />
            </button>
          </form>
          <span className={s.caption}>
            {config.auth === "local"
              ? "Local preview · your progress stays on this computer"
              : config.auth === "disabled"
                ? "Sign-in has not been configured. Ask your administrator."
                : config.self_signup_email_domains?.length
                  ? `New learners can sign up with ${config.self_signup_email_domains.map((domain) => `@${domain}`).join(" or ")}. Verify your email to start learning.`
                  : "Use your training account to save your progress."}
          </span>
        </section>
        <section className={s.welcomeVisual}>
          <div className={s.visualHeading}>
            <span>YOUR FIRST EXPERIMENT</span>
            <span>01 / FLEX FOUNDATIONS</span>
          </div>
          <Deck
            layout={{ stock: "D1", plate: "C2", tips: "B1", waste: "D3" }}
            locked
            large
          />
          <div className={s.visualFooter}>
            <span>
              <FlaskConical size={19} /> A little less, each time.
            </span>
            <span>
              Serial dilution <ArrowRight size={16} />
            </span>
          </div>
          <div className={s.floatingNote}>
            <span className={s.noteDot} />
            <div>
              Room to get it wrong.
              <small>Reset your experiment, not your confidence.</small>
            </div>
          </div>
        </section>
      </div>
      <footer className={s.welcomeFooter}>
        <span>LEARN BY DOING.</span>
        <span>01 Arrange your bench</span>
        <span>02 Build your method</span>
        <span>03 Learn from the result</span>
      </footer>
    </main>
  );
}

function Onboarding({
  profile,
  onSave,
  busy,
}: {
  profile: Profile;
  onSave: (p: Profile) => void;
  busy: boolean;
}) {
  const [step, setStep] = useState(0);
  const [name, setName] = useState(profile.name);
  const [experience, setExperience] = useState<Profile["experience"]>("new");
  return (
    <main className={s.onboarding}>
      <Brand />
      <div className={s.onboardBody}>
        <div className={s.onboardProgress}>
          {[0, 1, 2].map((n) => (
            <span key={n} className={n <= step ? s.done : ""} />
          ))}
        </div>
        <div className={s.eyebrow}>A QUICK HELLO · {step + 1} OF 3</div>
        {step === 0 ? (
          <>
            <h1>
              Make yourself
              <br />
              at home.
            </h1>
            <p>
              Your learning lab keeps your experiments and progress together.
            </p>
            <label>
              Your name
              <input
                value={name}
                maxLength={60}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
          </>
        ) : step === 1 ? (
          <>
            <h1>
              Every scientist
              <br />
              starts somewhere.
            </h1>
            <p>How familiar are you with liquid-handling robots?</p>
            <div className={s.choices}>
              {(
                [
                  [
                    "new",
                    "This is my first time",
                    "Let’s start with the basics.",
                  ],
                  [
                    "some",
                    "I’ve seen them in action",
                    "I know the idea. I want to practice.",
                  ],
                  [
                    "experienced",
                    "I’ve worked with them",
                    "I’m here to explore and refine.",
                  ],
                ] as const
              ).map(([value, title, detail]) => (
                <button
                  key={value}
                  className={experience === value ? s.chosen : ""}
                  onClick={() => setExperience(value)}
                >
                  <span>
                    <strong>{title}</strong>
                    <small>{detail}</small>
                  </span>
                  {experience === value ? (
                    <Check size={19} />
                  ) : (
                    <Circle size={19} />
                  )}
                </button>
              ))}
            </div>
          </>
        ) : (
          <>
            <h1>
              Try. Notice.
              <br />
              Try differently.
            </h1>
            <p>
              Lab Onboarding connects simulation training with supervised
              practice on real devices. Start here with liquid volumes, ideal
              dilution and tip use in a teaching model.
            </p>
            <div className={s.safetyNote}>
              <ShieldCheck size={25} />
              <div>
                <strong>Simulation · Teaching practice available</strong>
                <p>
                  Matterix will provide the connected digital twin once its
                  Ubuntu runtime is qualified.
                </p>
              </div>
            </div>
            <div className={s.safetyNote}>
              <Pipette size={25} />
              <div>
                <strong>Real devices · Not connected</strong>
                <p>
                  Supervised hardware training is a planned path. Simulation
                  practice does not grant permission to operate a real device.
                </p>
              </div>
            </div>
          </>
        )}
        <div className={s.onboardActions}>
          {step > 0 && (
            <button className={s.textButton} onClick={() => setStep(step - 1)}>
              <ArrowLeft size={16} /> Back
            </button>
          )}
          <button
            className={s.primary}
            disabled={busy || !name.trim()}
            onClick={() =>
              step < 2
                ? setStep(step + 1)
                : onSave({ name: name.trim(), experience, onboarded: true })
            }
          >
            {step === 2 ? "Open my workspace" : "Continue"}
            <ArrowRight size={17} />
          </button>
        </div>
      </div>
      <span className={s.caption}>A little practice goes a long way.</span>
    </main>
  );
}

function Dashboard({
  profile,
  courses,
  sessions,
  onCreate,
  onFirstLesson,
  onOpen,
  onNavigate,
  view,
}: {
  profile: Profile;
  courses: Course[];
  sessions: Session[];
  onCreate: () => void;
  onFirstLesson: () => void;
  onOpen: (run: Session) => void;
  onNavigate: (view: string) => void;
  view: string;
}) {
  const completed = sessions.filter((run) => run.assessment?.passed).length;
  return (
    <div className={s.dashboard}>
      <div className={s.pageHeading}>
        <div>
          <div className={s.eyebrow}>YOUR LEARNING WORKSPACE</div>
          <h1>
            {view === "history"
              ? "Every attempt teaches you."
              : `Welcome to the lab, ${profile.name}.`}
          </h1>
          <p>
            {view === "history"
              ? "Pick up an experiment where you left off."
              : "There’s no perfect first attempt. Let’s make a useful one."}
          </p>
        </div>
        <span className={s.dayLabel}>
          <span className={s.noteDot} /> Simulation only
        </span>
      </div>
      {view !== "history" && (
        <>
          <DiscoveryInvitation onNavigate={onNavigate} />
          <FirstLessonCard
            onStart={onFirstLesson}
            resume={sessions.some(
              (run) => run.experiment.course_id === "flex-first-transfer",
            )}
          />
          <div className={s.courseFeature}>
            <section>
              <span className={s.courseTag}>01 · FLEX FOUNDATIONS</span>
              <h2>
                {courses.find((course) => course.id === "flex-foundations")
                  ?.title ?? "A little less, each time."}
              </h2>
              <p>
                Turn one stock solution into three dilutions.
                <br />A small experiment with a lot to teach you.
              </p>
              <div className={s.courseMeta}>
                <span>
                  <Clock3 size={15} /> 15–20 minutes
                </span>
                <span>
                  <Layers3 size={15} /> Beginner friendly
                </span>
              </div>
              <button className={s.primary} onClick={onCreate}>
                Start an experiment <ArrowRight size={18} />
              </button>
            </section>
            <div className={s.dilutionArt}>
              {[100, 50, 25, 12.5].map((v, i) => (
                <div key={v}>
                  <div className={s.testTube}>
                    <div
                      style={{
                        height: `${60 - i * 8}%`,
                        opacity: 0.3 + v / 150,
                      }}
                    />
                  </div>
                  <strong>{v}%</strong>
                  <span>{i === 0 ? "STOCK" : `WELL A${i}`}</span>
                </div>
              ))}
            </div>
          </div>
          <div className={s.learningStrip}>
            <span>IN THIS EXPERIMENT</span>
            {[
              "Arrange your labware",
              "Compose a transfer",
              "Understand what happened",
            ].map((text, i) => (
              <div key={text}>
                <span>0{i + 1}</span>
                {text}
              </div>
            ))}
          </div>
          <div className={s.modelNote}>
            <CircleHelp size={17} />
            <p>
              <strong>A clear model, a clear boundary.</strong> This lesson uses
              ideal mixing and volume bookkeeping. Collision physics and
              chemical outcomes are outside this teaching model.
            </p>
          </div>
        </>
      )}
      <div className={s.sectionHeading}>
        <h2>
          Your experiments <span>{sessions.length}</span>
        </h2>
        <span>
          {completed} learning goal{completed === 1 ? "" : "s"} reached
        </span>
      </div>
      {sessions.length ? (
        <div className={s.experimentList}>
          {sessions.map((run) => (
            <button key={run.id} onClick={() => onOpen(run)}>
              <span className={s.experimentIcon}>
                <FlaskConical size={22} />
              </span>
              <span>
                <strong>{run.experiment.title}</strong>
                <small>
                  {new Date(run.created_at).toLocaleDateString("en-CA", {
                    month: "short",
                    day: "numeric",
                  })}{" "}
                  · {run.experiment.actions.length} steps · Teaching model
                </small>
              </span>
              <span className={`${s.status} ${s[run.status]}`}>
                {run.status === "faulted"
                  ? "Needs a rethink"
                  : run.assessment?.passed
                    ? "Goal reached"
                    : run.status}
              </span>
              <ArrowRight size={18} />
            </button>
          ))}
        </div>
      ) : (
        <div className={s.emptyState}>
          <Beaker size={24} />
          <div>
            <strong>Your first experiment belongs here.</strong>
            <p>
              Start the Flex lesson above. Every attempt is saved as you work.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

function Workspace({
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
          <div className={s.eyebrow}>FLEX FOUNDATIONS / EXPERIMENT</div>
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

export default function App() {
  const [config, setConfig] = useState<Config | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [courses, setCourses] = useState<Course[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [session, setSession] = useState<Session | null>(null);
  const [view, setView] = useState("learn");
  const [discoverySeed, setDiscoverySeed] = useState<Workflow | undefined>();
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [help, setHelp] = useState(false);
  const closeHelp = useCallback(() => setHelp(false), []);
  useDialog(help, closeHelp);
  const leaveGuard = useRef<(() => boolean) | null>(null);
  const navigationEpoch = useRef(0);
  const identityEpoch = useRef(0);
  const registerLeaveGuard = useCallback((guard: (() => boolean) | null) => {
    leaveGuard.current = guard;
  }, []);
  const refresh = useCallback(async () => {
    const [p, c, r] = await Promise.all([
      api<Profile>("/me"),
      api<Course[]>("/courses"),
      api<Session[]>("/sessions"),
    ]);
    setProfile(p);
    setCourses(c);
    setSessions(r);
    const id = window.location.hash.match(/^#\/lab\/([a-f0-9-]+)$/)?.[1];
    if (id) {
      setSession(await api<Session>(`/sessions/${id}`));
      setView("lab");
    } else {
      const route = window.location.hash.match(
        /^#\/(marketplace|discovery|connector|history)(?:\/([a-z]+))?$/,
      );
      if (route) {
        setView(route[1]);
        if (route[1] === "discovery")
          setDiscoverySeed(workflows.find((w) => w.id === route[2]));
      }
    }
  }, []);
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const c = await api<Config>("/config");
        await configureAuth(c);
        if (alive) setConfig(c);
        try {
          await refresh();
        } catch (e) {
          if (!(e instanceof ApiError && e.status === 401)) throw e;
        }
      } catch (e) {
        if (alive)
          setError(
            e instanceof Error ? e.message : "Could not open the workspace.",
          );
      } finally {
        if (alive) setLoading(false);
      }
    })();
    const unauthorized = () => {
      identityEpoch.current += 1;
      navigationEpoch.current += 1;
      setProfile(null);
      setSession(null);
    };
    window.addEventListener("academy:unauthorized", unauthorized);
    return () => {
      alive = false;
      window.removeEventListener("academy:unauthorized", unauthorized);
    };
  }, [refresh]);
  const showError = useCallback((message: string) => setError(message), []);
  const updateSession = useCallback((next: Session) => {
    setSession((current) => (current?.id === next.id ? next : current));
    setSessions((list) => [next, ...list.filter((r) => r.id !== next.id)]);
  }, []);
  const open = (run: Session, checkLeave = true) => {
    if (checkLeave && leaveGuard.current && !leaveGuard.current()) return;
    navigationEpoch.current += 1;
    setSession(run);
    setView("lab");
    window.location.hash = `/lab/${run.id}`;
    window.scrollTo(0, 0);
  };
  const nav = (target: string) => {
    // Keep the active connector subpage when reselecting its sidebar section.
    if (target === "connector" && view === "connector") return;
    if (leaveGuard.current && !leaveGuard.current()) return;
    navigationEpoch.current += 1;
    setView(target);
    setSession(null);
    window.history.replaceState(
      {},
      "",
      target === "learn" ? "/" : `/#/${target}`,
    );
    if (target === "discovery") setDiscoverySeed(undefined);
    window.scrollTo(0, 0);
  };
  const create = async (first = false) => {
    if (leaveGuard.current && !leaveGuard.current()) return;
    const originEpoch = navigationEpoch.current;
    const originIdentity = identityEpoch.current;
    setBusy(true);
    try {
      const run = await api<Session>(
        "/sessions",
        json(first ? firstTransfer() : {}),
      );
      if (originIdentity !== identityEpoch.current) return;
      setSessions((list) => [
        run,
        ...list.filter((item) => item.id !== run.id),
      ]);
      if (originEpoch !== navigationEpoch.current) return;
      open(run, false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const enter = async (name: string) => {
    identityEpoch.current += 1;
    setBusy(true);
    try {
      if (config?.auth === "cognito") await signIn();
      else {
        await api("/auth/guest", json({ name }));
        await refresh();
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      {error && (
        <div className={s.toast} role="alert">
          <AlertTriangle size={18} />
          <span>{error}</span>
          <button aria-label="Dismiss error" onClick={() => setError("")}>
            <X size={17} />
          </button>
        </div>
      )}
      {loading ? (
        <div className={s.loading}>
          <Brand />
          <p>Setting up your learning space…</p>
        </div>
      ) : !config ? (
        <div className={s.loading}>
          <h1>The workspace is unavailable.</h1>
          <p>Check the connection and try again.</p>
          <button
            className={s.primary}
            onClick={() => window.location.reload()}
          >
            Try again
          </button>
        </div>
      ) : !profile ? (
        <Welcome config={config} onEnter={enter} busy={busy} />
      ) : !profile.onboarded ? (
        <Onboarding
          profile={profile}
          busy={busy}
          onSave={async (p) => {
            setBusy(true);
            try {
              setProfile(await api<Profile>("/me", json(p, "PUT")));
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        />
      ) : (
        <div className={s.shell}>
          <aside className={s.sidebar}>
            <Brand small />
            <div className={s.sidebarLabel}>YOUR TRAINING</div>
            <nav>
              <button
                className={view === "learn" ? s.activeNav : ""}
                onClick={() => nav("learn")}
              >
                <BookOpen size={18} /> Learning lab
              </button>
              <button
                className={view === "discovery" ? s.activeNav : ""}
                onClick={() => nav("discovery")}
              >
                <Compass size={18} /> Discovery studio
              </button>
              <button
                className={view === "marketplace" ? s.activeNav : ""}
                onClick={() => nav("marketplace")}
              >
                <Store size={18} /> Workflow marketplace
              </button>
              <button
                className={view === "connector" ? s.activeNav : ""}
                onClick={() => nav("connector")}
              >
                <GitBranch size={18} /> Connector explorer
              </button>
              <button
                className={view === "history" ? s.activeNav : ""}
                onClick={() => nav("history")}
              >
                <History size={18} /> My experiments{" "}
                <span>{sessions.length}</span>
              </button>
              {view === "lab" && (
                <button className={s.activeNav}>
                  <FlaskConical size={18} /> Current experiment
                </button>
              )}
            </nav>
            <div className={s.sidebarBottom}>
              <div className={s.sidebarTip}>
                <Beaker size={22} />
                <strong>Practice makes progress.</strong>
                <p>
                  Your next attempt starts with what you learned from the last.
                </p>
              </div>
              <button className={s.helpButton} onClick={() => setHelp(true)}>
                <CircleHelp size={17} /> About this learning lab
              </button>
              <div className={s.user}>
                <span>{profile.name.slice(0, 1).toUpperCase()}</span>
                <div>
                  <strong>{profile.name}</strong>
                  <small>Learner workspace</small>
                </div>
                <button
                  aria-label="Sign out"
                  onClick={async () => {
                    if (leaveGuard.current && !leaveGuard.current()) return;
                    try {
                      identityEpoch.current += 1;
                      navigationEpoch.current += 1;
                      await signOut(config);
                      setProfile(null);
                      setSession(null);
                      setSessions([]);
                      window.history.replaceState({}, "", "/");
                    } catch (e) {
                      setError((e as Error).message);
                    }
                  }}
                >
                  <LogOut size={17} />
                </button>
              </div>
            </div>
          </aside>
          <main className={s.content}>
            <header className={s.topbar}>
              <span>
                <LayoutGrid size={15} /> Lab Onboarding{" "}
                <ChevronRight size={13} />{" "}
                {view === "lab"
                  ? "Flex foundations"
                  : view === "history"
                    ? "My experiments"
                    : view === "discovery"
                      ? "Discovery studio"
                      : view === "marketplace"
                        ? "Workflow marketplace"
                        : view === "connector"
                          ? "Connector explorer"
                          : "Learning lab"}
              </span>
              <span>
                <span className={s.noteDot} />{" "}
                {config.auth === "local"
                  ? "Local learning preview"
                  : "Training workspace"}
              </span>
            </header>
            {view === "marketplace" ? (
              <WorkflowMarketplace
                onAdapt={(item) => {
                  if (leaveGuard.current && !leaveGuard.current()) return;
                  navigationEpoch.current += 1;
                  setDiscoverySeed(item);
                  setSession(null);
                  setView("discovery");
                  window.history.replaceState(
                    {},
                    "",
                    `/#/discovery/${item.id}`,
                  );
                  window.scrollTo(0, 0);
                }}
              />
            ) : view === "discovery" ? (
              <DiscoveryStudio
                key={discoverySeed?.id ?? "blank"}
                seed={discoverySeed}
                navigationPending={busy}
                registerLeaveGuard={registerLeaveGuard}
                onPractice={() => {
                  if (!busy) create();
                }}
              />
            ) : view === "connector" ? (
              <ConnectorExplorer />
            ) : view === "lab" &&
              session?.experiment.course_id === "flex-first-transfer" ? (
              <LearningLab
                key={session.id}
                session={session}
                onChange={updateSession}
                onBack={() => nav("learn")}
                onError={showError}
                registerLeaveGuard={registerLeaveGuard}
              />
            ) : view === "lab" && session ? (
              <Workspace
                key={session.id}
                session={session}
                onChange={updateSession}
                onBack={() => nav("learn")}
                onError={showError}
                registerLeaveGuard={registerLeaveGuard}
              />
            ) : (
              <Dashboard
                profile={profile}
                courses={courses}
                sessions={sessions}
                onCreate={() => {
                  if (!busy) create();
                }}
                onFirstLesson={() => {
                  if (busy) return;
                  const existing = sessions.find(
                    (run) => run.experiment.course_id === "flex-first-transfer",
                  );
                  if (existing) open(existing);
                  else create(true);
                }}
                onOpen={open}
                onNavigate={nav}
                view={view}
              />
            )}
            <footer className={s.appFooter}>
              <span>LAB ONBOARDING</span>
              <span>Explore freely. Learn deliberately.</span>
              <span>Teaching model · v0.1</span>
            </footer>
          </main>
        </div>
      )}
      {help && (
        <div className={s.modalBackdrop} onClick={() => setHelp(false)}>
          <section
            className={s.modal}
            role="dialog"
            aria-modal="true"
            aria-labelledby="help-title"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className={s.closeButton}
              aria-label="Close help"
              onClick={() => setHelp(false)}
            >
              <X size={20} />
            </button>
            <Maximize2 size={28} />
            <h2 id="help-title">About Lab Onboarding</h2>
            <p>
              Learn laboratory automation, explore workflows and understand
              connectors. Training spans simulation and supervised work on real
              devices.
            </p>
            <p>
              Choose a lesson, arrange the deck and edit the action sequence.
              Run automatically or advance one step at a time. Review your
              observations, reset and try again.
            </p>
            <p>
              The current teaching model checks volume, capacity and tip-use
              rules. Deck placement is schematic; reachability, collisions and
              chemical outcomes are not evaluated. Matterix is the digital twin
              engine for the connected simulation path. Real-device training is
              planned; no physical robot is connected here.
            </p>
            <button className={s.primary} onClick={() => setHelp(false)}>
              Got it
              <Check size={16} />
            </button>
          </section>
        </div>
      )}
    </>
  );
}
