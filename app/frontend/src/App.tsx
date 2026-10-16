import {
  Suspense,
  lazy,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  ArrowRight,
  ArrowLeft,
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
  Plus,
  ShieldCheck,
  X,
  AlertTriangle,
  Circle,
  Pipette,
  Layers3,
  Compass,
  Store,
  GitBranch,
} from "lucide-react";
import { api, ApiError, configureAuth, json, signIn, signOut } from "./api";
import type { Config, Course, Profile, Session } from "./types";
import s from "./App.module.css";
import { useDialog } from "./useDialog";
import { firstTransfer } from "./learningContent";
import { workflows, type Workflow } from "./discoveryContent";
import {
  workspaceLabels,
  workspaceViews,
  type WorkspaceView,
} from "./workcellTypes";
import { Deck } from "./deck";
import { FirstLessonCard } from "./FirstLessonCard";
import { DiscoveryInvitation } from "./DiscoveryInvitation";

const SimulationLab = lazy(() => import("./SimulationLab"));
const LearningLab = lazy(() => import("./LearningLab"));
const ConnectorExplorer = lazy(() => import("./ConnectorExplorer"));
const Workcell = lazy(() => import("./Workcell"));
const DilutionWorkspace = lazy(() => import("./DilutionWorkspace"));
const WorkflowMarketplace = lazy(() =>
  import("./Discovery").then((m) => ({ default: m.WorkflowMarketplace })),
);
const DiscoveryStudio = lazy(() =>
  import("./Discovery").then((m) => ({ default: m.DiscoveryStudio })),
);

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

export default function App() {
  const [config, setConfig] = useState<Config | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [courses, setCourses] = useState<Course[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [session, setSession] = useState<Session | null>(null);
  const [view, setView] = useState("overview");
  const [workspaceRouteRevision, setWorkspaceRouteRevision] = useState(0);
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
  useEffect(() => {
    const routeChanged = (event: HashChangeEvent) => {
      const route = window.location.hash.match(
        /^#\/(overview|onboard|twin|readiness|runs)(?:\/([a-z0-9-]+))?$/,
      );
      if (!route && window.location.hash) return;
      if (leaveGuard.current && !leaveGuard.current()) {
        window.history.replaceState({}, "", event.oldURL);
        return;
      }
      navigationEpoch.current += 1;
      setSession(null);
      setView(route?.[1] ?? "overview");
      setWorkspaceRouteRevision((current) => current + 1);
    };
    window.addEventListener("hashchange", routeChanged);
    return () => window.removeEventListener("hashchange", routeChanged);
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
        /^#\/(overview|onboard|twin|readiness|runs|learn|marketplace|discovery|connector|history|sim)(?:\/([a-z0-9-]+))?$/,
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
    // Preserve the selected subpage/run when reselecting its sidebar section.
    if (
      (target === "connector" ||
        target === "sim" ||
        workspaceViews.includes(target as WorkspaceView)) &&
      view === target
    )
      return;
    if (leaveGuard.current && !leaveGuard.current()) return;
    navigationEpoch.current += 1;
    setView(target.split("/")[0]);
    setSession(null);
    window.history.replaceState(
      {},
      "",
      target === "overview" ? "/" : `/#/${target}`,
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
            <div className={s.sidebarLabel}>YOUR WORKCELL</div>
            <nav aria-label="Workcell navigation">
              {workspaceViews.map((target, index) => {
                const Icon = [LayoutGrid, Plus, Layers3, ShieldCheck, History][
                  index
                ];
                return (
                  <button
                    key={target}
                    className={view === target ? s.activeNav : ""}
                    aria-current={view === target ? "page" : undefined}
                    onClick={() => nav(target)}
                  >
                    <Icon size={18} />
                    {workspaceLabels[target]}
                  </button>
                );
              })}
            </nav>
            <div className={s.sidebarLabel}>LEARN & EXPLORE</div>
            <nav aria-label="Learning navigation">
              <button
                className={view === "sim" ? s.activeNav : ""}
                onClick={() => nav("sim")}
              >
                <FlaskConical size={18} /> Simulation lab
              </button>
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
                      setView("overview");
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
                {workspaceLabels[view] ??
                  (view === "lab"
                    ? "Flex foundations"
                    : view === "history"
                      ? "My experiments"
                      : view === "discovery"
                        ? "Discovery studio"
                        : view === "marketplace"
                          ? "Workflow marketplace"
                          : view === "connector"
                            ? "Connector explorer"
                            : view === "sim"
                              ? "Simulation lab"
                              : "Learning lab")}
              </span>
              <span>
                <span className={s.noteDot} />{" "}
                {config.auth === "local"
                  ? "Local learning preview"
                  : "Training workspace"}
              </span>
            </header>
            <Suspense
              fallback={
                <p className={s.pageLoading} role="status">
                  Loading…
                </p>
              }
            >
              {workspaceViews.includes(view as WorkspaceView) ? (
                <Workcell
                  key={`${view}:${workspaceRouteRevision}`}
                  view={view as WorkspaceView}
                  name={profile.name}
                  onNavigate={nav}
                  onOpen={open}
                  onSessionsLoaded={setSessions}
                  onSessionSaved={updateSession}
                  onFirstLesson={() => {
                    if (busy) return;
                    const existing = sessions.find(
                      (run) =>
                        run.experiment.course_id === "flex-first-transfer",
                    );
                    if (existing) open(existing);
                    else create(true);
                  }}
                  onCreate={() => {
                    if (!busy) create();
                  }}
                  registerLeaveGuard={registerLeaveGuard}
                />
              ) : view === "sim" ? (
                <SimulationLab />
              ) : view === "marketplace" ? (
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
                <DilutionWorkspace
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
                      (run) =>
                        run.experiment.course_id === "flex-first-transfer",
                    );
                    if (existing) open(existing);
                    else create(true);
                  }}
                  onOpen={open}
                  onNavigate={nav}
                  view={view}
                />
              )}
            </Suspense>
            <footer className={s.appFooter}>
              <span>LAB ONBOARDING</span>
              <span>Explore freely. Learn deliberately.</span>
              <span>
                {workspaceViews.includes(view as WorkspaceView)
                  ? "Physical readiness · unverified"
                  : view === "sim"
                    ? "Isaac / Matterix · v0.1"
                    : "Teaching model · v0.1"}
              </span>
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
