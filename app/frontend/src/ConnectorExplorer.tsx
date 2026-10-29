import { useEffect, useId, useState } from "react";
import {
  ArrowDown,
  ArrowRight,
  BookOpen,
  Check,
  Code2,
  ExternalLink,
  GitBranch,
  Pause,
  Play,
  RotateCcw,
} from "lucide-react";
import {
  connectorCommit,
  connectorExcerpts,
  connectorModules,
  sourceNodes,
  type ConnectorModule,
  type ExcerptId,
} from "./connectorContent";
import styles from "./ConnectorExplorer.module.css";
import { CapabilityMap, DevelopmentPath } from "./ConnectorDevelopment";

function SourcePanel({ id }: { id: ExcerptId }) {
  const excerpt = connectorExcerpts.find((item) => item.id === id)!;
  return (
    <div className={styles.source}>
      <div className={styles.sourceMeta}>
        <Code2 size={15} />
        <span>{excerpt.path}</span>
        <span>
          Lines {excerpt.start}–{excerpt.end}
        </span>
      </div>
      <pre tabIndex={0} aria-label="Verbatim connector source">
        <code>{excerpt.code}</code>
      </pre>
      <a href={excerpt.url} target="_blank" rel="noreferrer">
        Open this exact source <ExternalLink size={13} />
      </a>
    </div>
  );
}

function Glossary({ terms }: { terms: ConnectorModule["terms"] }) {
  const [selected, setSelected] = useState<string | null>(null);
  const panelId = useId();
  const current = terms.find((item) => item.term === selected);
  return (
    <aside className={styles.glossary} aria-label="Module glossary">
      <span className={styles.eyebrow}>New vocabulary · select a term</span>
      <div className={styles.terms}>
        {terms.map((item) => (
          <button
            key={item.term}
            aria-expanded={selected === item.term}
            aria-controls={panelId}
            onClick={() =>
              setSelected(selected === item.term ? null : item.term)
            }
          >
            {item.term}
          </button>
        ))}
      </div>
      <div id={panelId} aria-live="polite">
        {current && (
          <p>
            <strong>{current.term}:</strong> {current.definition}
          </p>
        )}
      </div>
    </aside>
  );
}

function Trace({ module }: { module: ConnectorModule }) {
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(false);
  useEffect(() => {
    if (!playing) return;
    const timer = window.setTimeout(() => {
      if (step >= module.steps.length - 1) setPlaying(false);
      else setStep((value) => value + 1);
    }, 1600);
    return () => window.clearTimeout(timer);
  }, [playing, step, module.steps.length]);
  const last = step === module.steps.length - 1;
  return (
    <section className={styles.trace} aria-label="Illustrated command trace">
      <div className={styles.traceHeading}>
        <div>
          <span className={styles.eyebrow}>Follow the request</span>
          <h3>The components in conversation</h3>
        </div>
        <span className={styles.badge}>
          Illustrated trace · no device connection
        </span>
      </div>
      <div className={styles.flow} aria-label="Data flow">
        {module.steps.map((item, index) => (
          <div className={styles.flowPart} key={`${module.id}-${index}`}>
            <button
              className={`${styles.actor} ${step === index ? styles.actorActive : ""} ${step > index ? styles.actorVisited : ""}`}
              onClick={() => {
                setPlaying(false);
                setStep(index);
              }}
              aria-label={`Trace step ${index + 1}: ${item.actor}`}
              aria-current={step === index ? "step" : undefined}
            >
              <span className={styles.actorNumber}>
                {String(index + 1).padStart(2, "0")}
              </span>
              <strong>{item.actor}</strong>
              <small>
                {index === step
                  ? item.packet
                  : index < step
                    ? "Explored"
                    : "Next in the trace"}
              </small>
            </button>
            {index < module.steps.length - 1 && (
              <ArrowRight
                className={`${styles.flowArrow} ${step > index ? styles.flowArrowVisited : ""}`}
                size={21}
                aria-hidden="true"
              />
            )}
          </div>
        ))}
      </div>
      <div
        className={styles.conversation}
        aria-live="polite"
        aria-atomic="false"
      >
        {module.steps.slice(0, step + 1).map((item, index) => (
          <div
            key={`${module.id}-${index}`}
            className={`${styles.message} ${index === step ? styles.messageCurrent : ""}`}
          >
            <span className={styles.avatar}>{index + 1}</span>
            <div>
              <strong>{item.actor}</strong>
              <p>{item.message}</p>
            </div>
          </div>
        ))}
      </div>
      <div className={styles.traceControls}>
        <button
          className={styles.primary}
          onClick={() => {
            setPlaying(false);
            setStep((value) => Math.min(value + 1, module.steps.length - 1));
          }}
          disabled={last}
        >
          Next step <ArrowRight size={15} />
        </button>
        <button
          className={styles.secondary}
          onClick={() => {
            if (last && !playing) setStep(0);
            setPlaying(!playing);
          }}
        >
          {playing ? <Pause size={14} /> : <Play size={14} />}
          {playing ? "Pause playback" : "Play trace"}
        </button>
        <button
          className={styles.textButton}
          onClick={() => {
            setPlaying(false);
            setStep(0);
          }}
        >
          <RotateCcw size={14} />
          Reset trace
        </button>
        <span role="status">
          Step {step + 1} of {module.steps.length}
        </span>
      </div>
    </section>
  );
}

function ModuleLesson({
  module,
  onCorrect,
}: {
  module: ConnectorModule;
  onCorrect: () => void;
}) {
  const [showCode, setShowCode] = useState(false);
  const [answer, setAnswer] = useState<number | null>(null);
  const [checked, setChecked] = useState(false);
  const right = checked && answer === module.correct;
  return (
    <article className={styles.lesson}>
      <div className={styles.scenario}>
        <span className={styles.eyebrow}>
          Start with a laboratory situation
        </span>
        <h2>{module.title}</h2>
        <p>{module.scenario}</p>
      </div>
      <Glossary terms={module.terms} />
      <Trace module={module} />
      <section className={styles.readCode}>
        <div className={styles.sectionHeading}>
          <div>
            <span className={styles.eyebrow}>Read the implementation</span>
            <h3>One excerpt, two ways to read it</h3>
          </div>
          <div
            className={styles.switch}
            role="group"
            aria-label="Source explanation mode"
          >
            <button aria-pressed={!showCode} onClick={() => setShowCode(false)}>
              <BookOpen size={14} />
              Plain English
            </button>
            <button aria-pressed={showCode} onClick={() => setShowCode(true)}>
              <Code2 size={14} />
              Actual code
            </button>
          </div>
        </div>
        {showCode ? (
          <SourcePanel id={module.id} />
        ) : (
          <div className={styles.translation}>
            {module.translation.map((paragraph, index) => (
              <div key={paragraph}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                <p>{paragraph}</p>
              </div>
            ))}
          </div>
        )}
        <div className={styles.takeaway}>
          <GitBranch size={20} />
          <p>{module.takeaway}</p>
        </div>
      </section>
      {module.id === "progress" && (
        <section className={styles.backends}>
          <h3>Three different simulation contexts</h3>
          <div className={styles.backendGrid}>
            <div>
              <span>01</span>
              <h4>Onboarding teaching model</h4>
              <p>
                Educational steps and arithmetic for practice. This course’s
                trace is a local illustration.
              </p>
            </div>
            <div>
              <span>02</span>
              <h4>Opentrons simulator</h4>
              <p>
                The connector can construct an OT3API simulator backend to
                exercise software behavior.
              </p>
            </div>
            <div>
              <span>03</span>
              <h4>Matterix / Isaac</h4>
              <p>
                A separate digital-twin runtime. Passing this lesson or a
                connector simulator test does not qualify an Isaac workflow.
              </p>
            </div>
          </div>
          <details className={styles.backendSource}>
            <summary>
              See how the connector selects simulator or physical hardware
            </summary>
            <SourcePanel id="backend" />
          </details>
        </section>
      )}
      <form
        className={styles.quiz}
        onSubmit={(event) => {
          event.preventDefault();
          if (answer === null) return;
          setChecked(true);
          if (answer === module.correct) onCorrect();
        }}
      >
        <span className={styles.eyebrow}>Apply the idea</span>
        <fieldset>
          <legend>{module.question}</legend>
          {module.answers.map((option, index) => (
            <label
              key={option}
              className={answer === index ? styles.optionSelected : ""}
            >
              <input
                type="radio"
                name={`quiz-${module.id}`}
                checked={answer === index}
                onChange={() => {
                  setAnswer(index);
                  setChecked(false);
                }}
              />
              <span>{option}</span>
            </label>
          ))}
        </fieldset>
        <button
          className={styles.primary}
          disabled={answer === null}
          type="submit"
        >
          Check understanding <ArrowRight size={15} />
        </button>
        {checked && (
          <div
            className={`${styles.feedback} ${right ? styles.correct : styles.retry}`}
            role="status"
          >
            <strong>
              {right
                ? "That reasoning holds."
                : "Look at the responsibility again."}
            </strong>
            <p>{module.explanation}</p>
          </div>
        )}
      </form>
    </article>
  );
}

function SourceMap() {
  const [selected, setSelected] = useState<ExcerptId>("request");
  const current = sourceNodes.find((item) => item.id === selected)!;
  const nodeButton = (id: ExcerptId) => {
    const node = sourceNodes.find((item) => item.id === id)!;
    return (
      <button
        className={`${styles.mapNode} ${selected === id ? styles.mapSelected : ""}`}
        aria-pressed={selected === id}
        onClick={() => setSelected(id)}
      >
        <span>{node.title}</span>
        <strong>{node.role}</strong>
        <small>
          Inspect source <ArrowRight size={12} />
        </small>
      </button>
    );
  };
  return (
    <section className={styles.sourceMap}>
      <div className={styles.sectionHeading}>
        <div>
          <span className={styles.eyebrow}>Architecture you can inspect</span>
          <h2>Curated source map</h2>
        </div>
        <span className={styles.badge}>
          Pinned source · {connectorCommit.slice(0, 7)}
        </span>
      </div>
      <p className={styles.mapIntro}>
        Select a component to read its responsibility and exact source. This map
        is curated from the pinned connector code; it is not an automatically
        generated CodeGraph index.
      </p>
      <div className={styles.graph} aria-label="Connector architecture map">
        <div className={styles.mainPath}>
          <span className={styles.graphLabel}>Command execution</span>
          {nodeButton("request")}
          <div className={styles.edge}>
            <ArrowDown size={18} />
            <span>calls the controller</span>
          </div>
          {nodeButton("controller")}
          <div className={styles.edge}>
            <ArrowDown size={18} />
            <span>awaits the configured OT3API</span>
          </div>
          <div className={styles.apiNode}>
            <strong>OT3API</strong>
            <small>Simulator or real hardware</small>
          </div>
        </div>
        <div className={styles.sidePath}>
          <span className={styles.graphLabel}>Related responsibilities</span>
          {nodeButton("backend")}
          <p>Initialization chooses the API implementation.</p>
          {nodeButton("authority")}
          <p>Separate ownership policy in connector-pe.</p>
          {nodeButton("progress")}
          <p>Reports emitted around the controller call.</p>
        </div>
      </div>
      <div className={styles.mapDetail} aria-live="polite">
        <span className={styles.eyebrow}>Selected component</span>
        <h3>{current.title}</h3>
        <p>{current.relationship}</p>
      </div>
      <SourcePanel id={selected} />
      <div className={styles.mapBoundary}>
        <strong>Where Lab Onboarding fits</strong>
        <p>
          This explorer teaches the connector’s design. It does not invoke SiLA,
          start a native simulation or connect this platform to physical
          hardware.
        </p>
      </div>
    </section>
  );
}

export default function ConnectorExplorer() {
  type View = "course" | "map" | "mapping" | "development";
  const [view, setCurrentView] = useState<View>(() => {
    const part = window.location.hash.split("/")[2];
    return part === "map" || part === "mapping" || part === "development"
      ? part
      : "course";
  });
  const setView = (next: View) => {
    setCurrentView(next);
    window.history.replaceState(
      {},
      "",
      next === "course" ? "/#/connector" : `/#/connector/${next}`,
    );
  };
  const [moduleIndex, setModuleIndex] = useState(0);
  const [understood, setUnderstood] = useState<string[]>([]);
  const current = connectorModules[moduleIndex];
  return (
    <div className={styles.explorer}>
      <header className={styles.hero}>
        <div>
          <h1>
            From an idea
            <br />
            to an instrument action.
          </h1>
          <p>
            Follow an action, compare the native API with its SiLA contract, and
            see how to build and verify a connector.
          </p>
        </div>
        <div className={styles.heroStamp}>
          <GitBranch size={34} strokeWidth={1.3} />
          <strong>
            Connector
            <br />
            explorer
          </strong>
        </div>
      </header>
      <div className={styles.courseBar}>
        <div
          className={styles.tabs}
          role="group"
          aria-label="Connector explorer views"
        >
          <button
            onClick={() => setView("course")}
            aria-pressed={view === "course"}
          >
            <BookOpen size={16} />
            Guided course
          </button>
          <button
            onClick={() => setView("mapping")}
            aria-pressed={view === "mapping"}
          >
            <Code2 size={16} /> API ↔ SiLA mapping
          </button>
          <button
            onClick={() => setView("development")}
            aria-pressed={view === "development"}
          >
            <ArrowRight size={16} /> Build a connector
          </button>
          <button onClick={() => setView("map")} aria-pressed={view === "map"}>
            <GitBranch size={16} />
            Source map
          </button>
        </div>
        <span>
          {understood.length} / 4 ideas checked{" "}
          <small>Guided course · in this visit</small>
        </span>
      </div>
      {view === "mapping" ? (
        <CapabilityMap onBuild={() => setView("development")} />
      ) : view === "development" ? (
        <DevelopmentPath onMapping={() => setView("mapping")} />
      ) : view === "map" ? (
        <SourceMap />
      ) : (
        <>
          <nav
            className={styles.moduleNav}
            aria-label="Connector course modules"
          >
            {connectorModules.map((module, index) => (
              <button
                key={module.id}
                className={moduleIndex === index ? styles.moduleActive : ""}
                aria-current={moduleIndex === index ? "step" : undefined}
                onClick={() => setModuleIndex(index)}
              >
                <span className={styles.moduleNumber}>
                  {understood.includes(module.id) ? (
                    <Check size={18} />
                  ) : (
                    String(index + 1).padStart(2, "0")
                  )}
                </span>
                <strong>{module.title}</strong>
                <small>{module.subtitle}</small>
              </button>
            ))}
          </nav>
          <ModuleLesson
            key={current.id}
            module={current}
            onCorrect={() =>
              setUnderstood((value) =>
                value.includes(current.id) ? value : [...value, current.id],
              )
            }
          />
          <footer className={styles.lessonFooter}>
            <span>
              Module {moduleIndex + 1} of 4 · {current.title}
            </span>
            <button
              className={styles.secondary}
              onClick={() => {
                if (moduleIndex < connectorModules.length - 1) {
                  setModuleIndex((value) => value + 1);
                  window.scrollTo({ top: 0, behavior: "instant" });
                } else {
                  setView("map");
                  window.scrollTo({ top: 0, behavior: "instant" });
                }
              }}
            >
              {moduleIndex < connectorModules.length - 1
                ? "Next module"
                : "Explore the source map"}
              <ArrowRight size={15} />
            </button>
          </footer>
        </>
      )}
      <div className={styles.provenance}>
        Teaching content based on{" "}
        <a
          href={`https://github.com/AccelerationConsortium/opentrons-flex/tree/${connectorCommit}`}
          target="_blank"
          rel="noreferrer"
        >
          AccelerationConsortium/opentrons-flex <ExternalLink size={12} />
        </a>{" "}
        · commit {connectorCommit.slice(0, 12)}. Source review does not
        establish physical robot acceptance.
      </div>
    </div>
  );
}
