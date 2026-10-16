import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowDown,
  ArrowRight,
  ArrowUp,
  BookOpen,
  Check,
  ExternalLink,
  FlaskConical,
  Search,
  X,
} from "lucide-react";
import { api, json } from "./api";
import {
  workflows,
  methods,
  gantryConcepts,
  newBrief,
  type Brief,
  type Notebook,
  type Workflow,
} from "./discoveryContent";
import s from "./Discovery.module.css";

function WorkflowArt({ item }: { item: Workflow }) {
  const colors = [
    "#315e50",
    "#b78047",
    "#58668a",
    "#945c71",
    "#466e7d",
    "#7b7255",
  ];
  const color = colors[workflows.indexOf(item)];
  return (
    <svg
      viewBox="0 0 400 180"
      className={s.art}
      aria-hidden="true"
      style={{ color }}
    >
      <defs>
        <pattern
          id={`dots-${item.id}`}
          width="16"
          height="16"
          patternUnits="userSpaceOnUse"
        >
          <circle cx="1" cy="1" r="1" fill="currentColor" opacity=".12" />
        </pattern>
      </defs>
      <rect width="400" height="180" fill={`url(#dots-${item.id})`} />
      <path
        d="M78 87H172M225 87H317M320 118V146H80V118"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeDasharray="5 5"
        opacity=".45"
      />
      <g transform="translate(42 32)">
        <path
          d="M20 5H52M25 5V42L8 78Q4 89 18 89H54Q68 89 64 78L47 42V5"
          fill="#fffefa"
          stroke="currentColor"
          strokeWidth="2"
        />
        <path
          d="M19 62H54L64 81Q64 89 54 89H18Q7 89 9 81Z"
          fill="currentColor"
          opacity=".3"
        />
        {[0, 1, 2].map((i) => (
          <circle
            key={i}
            cx={25 + i * 10}
            cy={71 - (i % 2) * 6}
            r="3"
            fill="currentColor"
          />
        ))}
      </g>
      <g transform="translate(166 52)">
        <rect
          width="70"
          height="70"
          rx="8"
          fill="#fffefa"
          stroke="currentColor"
          strokeWidth="2"
        />
        {Array.from({ length: 9 }, (_, i) => (
          <circle
            key={i}
            cx={17 + (i % 3) * 18}
            cy={17 + Math.floor(i / 3) * 18}
            r="6"
            fill="currentColor"
            opacity={0.2 + (i % 3) * 0.2}
          />
        ))}
      </g>
      <g transform="translate(289 50)">
        <rect
          width="67"
          height="74"
          rx="5"
          fill="#fffefa"
          stroke="currentColor"
          strokeWidth="2"
        />
        <path
          d="M10 57H57M10 15V57M13 48L25 34L36 40L51 19"
          fill="none"
          stroke="currentColor"
          strokeWidth="3"
        />
        <circle cx="51" cy="19" r="4" fill="currentColor" />
      </g>
      <text x="78" y="169" textAnchor="middle">
        PREPARE
      </text>
      <text x="201" y="169" textAnchor="middle">
        TEST
      </text>
      <text x="322" y="169" textAnchor="middle">
        OPTIMIZE
      </text>
    </svg>
  );
}

export function WorkflowMarketplace({
  onAdapt,
}: {
  onAdapt: (item: Workflow) => void;
}) {
  const [query, setQuery] = useState("");
  const [domain, setDomain] = useState("All domains");
  const [selected, setSelected] = useState<Workflow | null>(null);
  const shown = workflows.filter(
    (w) =>
      (domain === "All domains" || w.domain === domain) &&
      [w.title, w.paper, w.platform, w.domain, w.prepare, w.test]
        .join(" ")
        .toLowerCase()
        .includes(query.toLowerCase().trim()),
  );
  if (selected)
    return (
      <div className={s.page}>
        <button className={s.textButton} onClick={() => setSelected(null)}>
          ← Back to workflows
        </button>
        <div className={s.detailHero}>
          <div>
            <span className={s.eyebrow}>
              {selected.domain.toUpperCase()} / {selected.year}
            </span>
            <h1>{selected.title}</h1>
            <p>{selected.question}</p>
            <div className={s.tags}>
              <span>Published method</span>
              <span>{selected.kind}</span>
              <span>Design inspiration</span>
            </div>
          </div>
          <WorkflowArt item={selected} />
        </div>
        <section className={s.source}>
          <BookOpen size={22} />
          <div>
            <h2>{selected.paper}</h2>
            <p>
              {selected.authors} · {selected.journal} · {selected.year}
            </p>
            <a href={selected.url} target="_blank" rel="noreferrer">
              Read the primary paper <ExternalLink size={14} />
            </a>
            <small>DOI: {selected.doi} · Source checked 1 October 2026</small>
            {selected.note && <p>{selected.note}</p>}
          </div>
        </section>
        <section className={s.section}>
          <div className={s.sectionHeading}>
            <h2>The published workflow</h2>
            <span>{selected.platform}</span>
          </div>
          <div className={s.phases}>
            {[
              ["01", "Prepare samples", selected.prepare],
              ["02", "Test a property", selected.test],
              [
                "03",
                selected.kind === "Screening"
                  ? "Interpret the screen"
                  : "Choose what comes next",
                selected.optimize,
              ],
            ].map(([n, title, body]) => (
              <article key={n}>
                <span>{n}</span>
                <h3>{title}</h3>
                <p>{body}</p>
              </article>
            ))}
          </div>
        </section>
        <section className={s.adaptation}>
          <div>
            <span className={s.eyebrow}>
              WORKFLOW ADAPTATION / NOT YET VALIDATED
            </span>
            <h2>What could you borrow for Flex?</h2>
            <p>{selected.adaptation}</p>
            <h3>Outside the liquid handler</h3>
            <p>{selected.external}</p>
          </div>
          <aside>
            <h3>A question to take with you</h3>
            <p>{selected.prompt}</p>
            <button className={s.primary} onClick={() => onAdapt(selected)}>
              Adapt this workflow <ArrowRight size={16} />
            </button>
            <small>
              Creates a design brief. This paper is not an executable protocol.
            </small>
          </aside>
        </section>
      </div>
    );
  return (
    <div className={s.page}>
      <header className={s.hero}>
        <span className={s.eyebrow}>THE RESEARCH SHELF</span>
        <h1>Workflow marketplace</h1>
        <p>Borrow a method. Combine an idea. Find a new question.</p>
        <small>
          A curated collection of published research, translated into
          experimental building blocks.
        </small>
      </header>
      <div className={s.searchBar}>
        <label>
          <Search size={19} />
          <input
            aria-label="Search workflows"
            placeholder="Search materials, methods or platforms…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <select
          aria-label="Filter by domain"
          value={domain}
          onChange={(e) => setDomain(e.target.value)}
        >
          {["All domains", ...new Set(workflows.map((w) => w.domain))].map(
            (d) => (
              <option key={d}>{d}</option>
            ),
          )}
        </select>
      </div>
      <div className={s.sectionHeading}>
        <span aria-live="polite">
          {shown.length} research workflow{shown.length === 1 ? "" : "s"}
        </span>
        <span>Published methods · Flex adaptations require qualification</span>
      </div>
      <div className={s.marketGrid}>
        {shown.map((item) => (
          <article className={s.workflowCard} key={item.id}>
            <WorkflowArt item={item} />
            <div className={s.cardBody}>
              <div className={s.cardMeta}>
                <span>{item.domain}</span>
                <span>{item.year}</span>
              </div>
              <h2>{item.title}</h2>
              <p>{item.question}</p>
              <div className={s.tags}>
                <span>{item.kind}</span>
                <span>{item.journal}</span>
              </div>
              <button
                onClick={() => {
                  setSelected(item);
                  window.scrollTo(0, 0);
                }}
                aria-label={`Explore ${item.title}`}
              >
                Explore workflow <ArrowRight size={18} />
              </button>
            </div>
          </article>
        ))}
      </div>
      {!shown.length && (
        <div className={s.empty}>
          <h2>No matching workflows yet.</h2>
          <p>Try a broader material or method, or reset the filters.</p>
          <button
            className={s.secondary}
            onClick={() => {
              setQuery("");
              setDomain("All domains");
            }}
          >
            Reset filters
          </button>
        </div>
      )}
      <p className={s.note}>
        This first collection is manually researched and curated. Search filters
        this collection; it does not search the live web. Cards contain no
        verified Flex recipes or simulated chemical results.
      </p>
    </div>
  );
}

function DiscoveryLoop() {
  const [stage, setStage] = useState(0);
  const [answer, setAnswer] = useState("");
  return (
    <section className={s.loopLesson} aria-label="Learn the discovery loop">
      <div className={s.stageNav}>
        {["Prepare samples", "Test a property", "Optimize the next batch"].map(
          (name, i) => (
            <button
              key={name}
              aria-pressed={stage === i}
              className={stage === i ? s.active : ""}
              onClick={() => setStage(i)}
            >
              <span>0{i + 1}</span>
              {name}
              <ArrowRight size={17} />
            </button>
          ),
        )}
      </div>
      <div className={s.loopBody}>
        <div>
          <span className={s.eyebrow}>
            ONE SAMPLE ID THROUGH THE WHOLE LOOP
          </span>
          <h2>
            {
              [
                "Make a comparison you can trust.",
                "Turn a sample into an observation.",
                "Let evidence change the next experiment.",
              ][stage]
            }
          </h2>
          <p>
            {
              [
                "Choose what varies, what stays fixed and how many repeats you need. A robot can repeat the wrong comparison very precisely.",
                "Preserve sample identity, units, processing history and uncertainty. Completing a dispense is not a measurement of a material property.",
                "Balance a promising region with an uncertain one. Repeating a result can be more informative than testing a new recipe.",
              ][stage]
            }
          </p>
          <div className={s.identity}>
            <strong>Sample B-02</strong>
            <span>Recipe + process history</span>
            <ArrowRight size={16} />
            <span>Measurement + uncertainty</span>
            <ArrowRight size={16} />
            <span>Next-batch decision</span>
          </div>
        </div>
        {stage === 0 ? (
          <div className={s.sampleGrid}>
            {[20, 40, 60].map((fraction, i) => (
              <div key={fraction}>
                <strong>Recipe {String.fromCharCode(65 + i)}</strong>
                <div className={s.sample}>
                  <i style={{ height: `${fraction}%` }} />
                </div>
                <span>
                  {fraction}% A / {100 - fraction}% B
                </span>
                <small>Same total volume · two repeats</small>
              </div>
            ))}
            <p>
              Illustrative two-component design; no chemical recipe or outcome
              is implied.
            </p>
          </div>
        ) : stage === 1 ? (
          <div className={s.observations}>
            <span className={s.eyebrow}>
              ILLUSTRATIVE DATA / ARBITRARY UNITS
            </span>
            <table>
              <thead>
                <tr>
                  <th>Recipe</th>
                  <th>Repeat 1</th>
                  <th>Repeat 2</th>
                </tr>
              </thead>
              <tbody>
                {[
                  ["A", 4, 5],
                  ["B", 7, 8],
                  ["C", 6, 10],
                ].map((row) => (
                  <tr key={row[0]}>
                    {row.map((v, i) => (
                      <td key={i}>{v}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            <p>
              C has the highest single value, but its two repeats disagree more.
              These invented observations teach reasoning; they are not
              simulator or paper data.
            </p>
          </div>
        ) : (
          <fieldset className={s.question}>
            <legend>
              Given A: 4, 5; B: 7, 8; C: 6, 10, what is a useful next step?
            </legend>
            {[
              ["highest", "Declare C the winner from its value of 10."],
              [
                "repeat",
                "Repeat B and C, checking preparation and measurement variation.",
              ],
            ].map(([value, label]) => (
              <label key={value}>
                <input
                  type="radio"
                  name="next-batch"
                  checked={answer === value}
                  onChange={() => setAnswer(value)}
                />
                {label}
              </label>
            ))}
            {answer && (
              <p role="status">
                {answer === "repeat"
                  ? "Yes. Investigate reproducibility before treating one high value as an improvement. Then use the observations to choose the next region."
                  : "A single high value is not enough. Compare repeatability and uncertainty before choosing the next batch."}
              </p>
            )}
          </fieldset>
        )}
      </div>
    </section>
  );
}

function GantryExplorer({
  value,
  onChange,
}: {
  value: Brief["gantry"];
  onChange: (value: Brief["gantry"]) => void;
}) {
  const [visit, setVisit] = useState(0);
  const concept = gantryConcepts.find((c) => c.id === value)!;
  return (
    <section className={s.section}>
      <div className={s.sectionHeading}>
        <div>
          <span className={s.eyebrow}>MOTION IS A DESIGN RESOURCE</span>
          <h2>What else could the gantry help you do?</h2>
        </div>
      </div>
      <div className={s.gantry}>
        <div className={s.gantryOptions}>
          {gantryConcepts.map((c) => (
            <button
              key={c.id}
              aria-pressed={value === c.id}
              className={value === c.id ? s.active : ""}
              onClick={() => {
                onChange(c.id);
                setVisit(0);
              }}
            >
              <strong>{c.title}</strong>
              <small>{c.status}</small>
            </button>
          ))}
        </div>
        <div className={s.gantryBoard}>
          <svg
            viewBox="0 0 360 230"
            role="img"
            aria-label={`Conceptual gantry visiting sample ${visit + 1}; not a calibrated Flex deck`}
          >
            <rect
              x="24"
              y="22"
              width="312"
              height="160"
              rx="10"
              fill="#eff1e9"
              stroke="#c1cbbd"
            />
            {Array.from({ length: 6 }, (_, i) => (
              <g key={i}>
                <rect
                  x={55 + (i % 3) * 100}
                  y={45 + Math.floor(i / 3) * 75}
                  width="50"
                  height="42"
                  rx="6"
                  fill={visit === i ? "#d9a466" : "#fffefa"}
                  stroke="#537363"
                />
                <text
                  x={80 + (i % 3) * 100}
                  y={71 + Math.floor(i / 3) * 75}
                  textAnchor="middle"
                >
                  S{i + 1}
                </text>
              </g>
            ))}
            <path
              d="M80 67H280V142H80"
              stroke="#537363"
              strokeDasharray="5 5"
              fill="none"
            />
            <line
              x1="24"
              y1={32 + Math.floor(visit / 3) * 75}
              x2="336"
              y2={32 + Math.floor(visit / 3) * 75}
              stroke="#315e50"
              strokeWidth="7"
            />
            <g
              transform={`translate(${80 + (visit % 3) * 100} ${32 + Math.floor(visit / 3) * 75})`}
            >
              <rect
                x="-12"
                y="-10"
                width="24"
                height="26"
                rx="3"
                fill="#315e50"
              />
              <path d="M-4 16V25H4V16" fill="#b78047" />
            </g>
            <text x="180" y="213" textAnchor="middle">
              Concept board · sample positions, not deck slots
            </text>
          </svg>
          <button
            className={s.secondary}
            onClick={() => setVisit((v) => (v + 1) % 6)}
          >
            Visit next sample <ArrowRight size={15} />
          </button>
          <small role="status">
            Position {visit + 1} of 6 · illustrative route, not a motion plan
          </small>
        </div>
        <div className={s.gantryExplanation}>
          <span className={s.eyebrow}>{concept.status}</span>
          <h3>{concept.title}</h3>
          <p>{concept.description}</p>
          <h4>What must be established?</h4>
          <p>{concept.requirements}</p>
          <a
            href="https://docs.opentrons.com/flex/system-description/robot/"
            target="_blank"
            rel="noreferrer"
          >
            Flex motion reference <ExternalLink size={13} />
          </a>
          <a
            href="https://docs.opentrons.com/flex/labware/gripper/"
            target="_blank"
            rel="noreferrer"
          >
            Gripper compatibility reference <ExternalLink size={13} />
          </a>
        </div>
      </div>
    </section>
  );
}

export function DiscoveryStudio({
  seed,
  navigationPending,
  registerLeaveGuard,
  onPractice,
}: {
  seed?: Workflow;
  navigationPending: boolean;
  registerLeaveGuard: (guard: (() => boolean) | null) => void;
  onPractice: () => void;
}) {
  const [brief, setBrief] = useState<Brief>(() => newBrief(seed));
  const [baseline, setBaseline] = useState(() => JSON.stringify(brief));
  const [notebook, setNotebook] = useState<Notebook | null>(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const dirty = JSON.stringify(brief) !== baseline;
  const operation = useRef(false);
  const mounted = useRef(true);
  const load = useCallback(async () => {
    if (operation.current) return;
    operation.current = true;
    setBusy(true);
    try {
      const next = await api<Notebook>("/discovery");
      if (mounted.current) {
        setNotebook(next);
        setError("");
      }
    } catch (e) {
      if (mounted.current) setError((e as Error).message);
    } finally {
      operation.current = false;
      if (mounted.current) setBusy(false);
    }
  }, []);
  useEffect(() => {
    mounted.current = true;
    void load();
    return () => {
      mounted.current = false;
    };
  }, [load]);
  useEffect(() => {
    const guard = () =>
      !dirty ||
      window.confirm(
        "Leave this unsaved design? Your last saved version will remain in your notebook.",
      );
    registerLeaveGuard(guard);
    const before = (e: BeforeUnloadEvent) => {
      if (dirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", before);
    return () => {
      registerLeaveGuard(null);
      window.removeEventListener("beforeunload", before);
    };
  }, [dirty, registerLeaveGuard]);
  function change(patch: Partial<Brief>) {
    if (operation.current || navigationPending) return;
    setBrief((b) => ({ ...b, ...patch }));
    setSaved(false);
  }
  function select(next: Brief) {
    if (operation.current || navigationPending) return;
    if (dirty && !window.confirm("Replace this unsaved design?")) return;
    setBrief(next);
    setBaseline(JSON.stringify(next));
    setSaved(false);
    setError("");
  }
  async function save() {
    if (!notebook || operation.current || conflicting) return;
    operation.current = true;
    setBusy(true);
    setError("");
    try {
      const next = await api<Notebook>(
        "/discovery",
        json(
          {
            expected_version: notebook.version,
            briefs: [
              brief,
              ...notebook.briefs.filter((b) => b.id !== brief.id),
            ],
          },
          "PUT",
        ),
      );
      if (mounted.current) {
        setNotebook(next);
        setBaseline(JSON.stringify(brief));
        setSaved(true);
      }
    } catch (e) {
      if (mounted.current)
        setError(
          `${(e as Error).message} Your draft is still here. Reload saved designs before retrying; review an existing saved design before replacing it.`,
        );
    } finally {
      operation.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  const latest = notebook?.briefs.find((b) => b.id === brief.id);
  const conflicting =
    !!latest &&
    JSON.stringify(latest) !== baseline &&
    JSON.stringify(latest) !== JSON.stringify(brief);
  const source = workflows.find((w) => w.id === brief.source_id);
  const valid =
    [
      brief.title,
      brief.objective,
      brief.variables,
      brief.measurement,
      brief.decision,
      brief.controls,
    ].every((v) => v.trim()) && brief.methods.length > 0;
  const full =
    notebook !== null &&
    notebook.briefs.length >= 20 &&
    !notebook.briefs.some((b) => b.id === brief.id);
  return (
    <div className={s.page} aria-busy={navigationPending}>
      {navigationPending && (
        <p role="status" className={s.note}>
          Opening the teaching sandbox… Your design is locked while this request
          finishes.
        </p>
      )}
      <fieldset className={s.studioBody} disabled={navigationPending || busy}>
        <header className={s.hero}>
          <span className={s.eyebrow}>DESIGN BEFORE AUTOMATION</span>
          <h1>Discovery studio</h1>
          <p>The pipette prepares a sample. You design what we learn.</p>
          <small>
            Use Prepare → Test → Optimize as a map for experimental thinking,
            with controls and sample history connecting every stage.
          </small>
        </header>
        <DiscoveryLoop />
        <section className={s.section}>
          <div className={s.sectionHeading}>
            <div>
              <span className={s.eyebrow}>YOUR EXPERIMENT / DESIGN ONLY</span>
              <h2>Compose a preparation route</h2>
            </div>
            <span>{brief.methods.length} methods selected</span>
          </div>
          {source && (
            <div className={s.sourceNote}>
              <BookOpen size={17} />
              <span>
                Inspired by{" "}
                <a href={source.url} target="_blank" rel="noreferrer">
                  {source.title} ({source.year})
                </a>
                .{" "}
                <strong>
                  Write your own objective and measurement plan below.
                </strong>
              </span>
            </div>
          )}
          <div className={s.methodGrid}>
            {methods.map((method) => (
              <button
                key={method.id}
                aria-pressed={brief.methods.includes(method.id)}
                className={
                  brief.methods.includes(method.id) ? s.selectedMethod : ""
                }
                onClick={() =>
                  change({
                    methods: brief.methods.includes(method.id)
                      ? brief.methods.filter((id) => id !== method.id)
                      : [...brief.methods, method.id],
                  })
                }
              >
                <span className={s.methodCheck}>
                  {brief.methods.includes(method.id) ? (
                    <Check size={16} />
                  ) : (
                    <span>+</span>
                  )}
                </span>
                <small>{method.tag}</small>
                <h3>{method.name}</h3>
                <p>{method.description}</p>
              </button>
            ))}
          </div>
          <div className={s.route}>
            <h3>Your conceptual sequence</h3>
            {brief.methods.length === 0 ? (
              <p>Select at least one preparation method above.</p>
            ) : (
              <ol>
                {brief.methods.map((id, i) => {
                  const m = methods.find((m) => m.id === id)!;
                  return (
                    <li key={id}>
                      <span className={s.order}>{i + 1}</span>
                      <div>
                        <strong>{m.name}</strong>
                        <p>{m.consider}</p>
                      </div>
                      <div className={s.reorder}>
                        <button
                          aria-label={`Move ${m.name} earlier`}
                          disabled={i === 0}
                          onClick={() => {
                            const next = [...brief.methods];
                            [next[i - 1], next[i]] = [next[i], next[i - 1]];
                            change({ methods: next });
                          }}
                        >
                          <ArrowUp size={16} />
                        </button>
                        <button
                          aria-label={`Move ${m.name} later`}
                          disabled={i === brief.methods.length - 1}
                          onClick={() => {
                            const next = [...brief.methods];
                            [next[i + 1], next[i]] = [next[i], next[i + 1]];
                            change({ methods: next });
                          }}
                        >
                          <ArrowDown size={16} />
                        </button>
                        <button
                          aria-label={`Remove ${m.name}`}
                          onClick={() =>
                            change({
                              methods: brief.methods.filter((m) => m !== id),
                            })
                          }
                        >
                          <X size={16} />
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ol>
            )}
            <p className={s.note}>
              Method order is a design proposal. Chemical compatibility, timing
              and device capabilities have not been validated.
            </p>
          </div>
        </section>
        <GantryExplorer
          value={brief.gantry}
          onChange={(gantry) => change({ gantry })}
        />
        <section className={s.briefSection}>
          <div>
            <span className={s.eyebrow}>CLOSE THE LOOP ON PAPER FIRST</span>
            <h2>Write your experiment brief</h2>
            <p>
              A useful plan says what will change, what will be measured, and
              how the result changes your next decision.
            </p>
            <div className={s.practice}>
              <FlaskConical size={25} />
              <h3>Need to practice a building block?</h3>
              <p>
                Try serial dilution in the teaching sandbox. It models volume
                and ideal mixing; it does not execute this brief.
              </p>
              <button className={s.secondary} onClick={onPractice}>
                Practice liquid handling <ArrowRight size={16} />
              </button>
            </div>
          </div>
          <form
            className={s.briefForm}
            onSubmit={(e) => {
              e.preventDefault();
              void save();
            }}
          >
            <label>
              Design title
              <input
                maxLength={100}
                disabled={busy}
                required
                value={brief.title}
                onChange={(e) => change({ title: e.target.value })}
              />
            </label>
            {(
              [
                [
                  "objective",
                  "What do you want to learn?",
                  "Example: Does changing the blend ratio improve a measurable property?",
                ],
                [
                  "variables",
                  "Prepare · What changes and what stays fixed?",
                  "Define ingredients, ranges, process order and fixed conditions.",
                ],
                [
                  "measurement",
                  "Test · What will you measure, and how?",
                  "Name the instrument, metric, units and how results link to sample IDs.",
                ],
                [
                  "decision",
                  "Optimize · How will you choose the next experiment?",
                  "State a decision rule, constraints and when to repeat instead of exploring.",
                ],
                [
                  "controls",
                  "What controls and repeats make the comparison trustworthy?",
                  "Include a reference or blank, repeat count and sources of variation.",
                ],
              ] as const
            ).map(([field, label, placeholder]) => (
              <label key={field}>
                {label}
                <textarea
                  maxLength={600}
                  disabled={busy}
                  required
                  rows={3}
                  value={brief[field]}
                  placeholder={placeholder}
                  onChange={(e) => change({ [field]: e.target.value })}
                />
              </label>
            ))}
            <div className={s.saveBar}>
              <button
                className={s.primary}
                type="submit"
                disabled={!valid || !notebook || busy || full || conflicting}
              >
                {busy ? "Saving…" : "Save design brief"}
                <Check size={17} />
              </button>
              <small>
                Private notebook ·{" "}
                {notebook
                  ? `${notebook.briefs.length}/20 saved designs`
                  : "Loading notebook…"}{" "}
                · Design only
              </small>
            </div>
            {conflicting && (
              <div className={s.error} role="alert">
                <p>
                  A newer version of this design is saved. Open it from the
                  notebook below to review it, or keep your current draft as a
                  separate design.
                </p>
                <button
                  type="button"
                  className={s.secondary}
                  disabled={busy || (notebook?.briefs.length ?? 0) >= 20}
                  onClick={() =>
                    change({
                      id: crypto.randomUUID(),
                      title: `${brief.title.slice(0, 93)} (copy)`,
                    })
                  }
                >
                  Keep my draft as a new design
                </button>
              </div>
            )}
            {full && (
              <p role="alert">
                This notebook holds 20 designs. Open an existing design to
                revise it.
              </p>
            )}
            {saved && (
              <p className={s.success} role="status">
                Design saved to your notebook. It is not an executable protocol.
              </p>
            )}
            {error && (
              <div className={s.error} role="alert">
                <p>{error}</p>
                <button
                  type="button"
                  className={s.secondary}
                  disabled={busy}
                  onClick={() => void load()}
                >
                  Reload saved designs
                </button>
              </div>
            )}
          </form>
        </section>
        <section className={s.section}>
          <div className={s.sectionHeading}>
            <h2>Your design notebook</h2>
            <button
              className={s.secondary}
              onClick={() => select(newBrief())}
              disabled={busy}
            >
              New design
            </button>
          </div>
          {notebook?.briefs.length ? (
            <div className={s.notebook}>
              {notebook.briefs.map((b) => (
                <button key={b.id} disabled={busy} onClick={() => select(b)}>
                  <BookOpen size={22} />
                  <span>
                    <strong>{b.title}</strong>
                    <small>
                      {b.methods.length} preparation methods · Design only
                    </small>
                  </span>
                  <ArrowRight size={17} />
                </button>
              ))}
            </div>
          ) : (
            <p className={s.note}>
              Saved briefs will appear here. A design can combine ideas from
              papers without claiming their results.
            </p>
          )}
        </section>
      </fieldset>
    </div>
  );
}
