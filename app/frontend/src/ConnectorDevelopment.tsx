import { useState } from "react";
import {
  ArrowDown,
  ArrowLeftRight,
  ArrowRight,
  Check,
  Code2,
  ExternalLink,
} from "lucide-react";
import {
  mappings,
  developmentSteps,
  sourceUrl,
  type Mapping,
  type DevelopmentSourceId,
} from "./connectorDevelopmentContent";
import { developmentSources } from "./connectorDevelopmentSources";
import s from "./ConnectorDevelopment.module.css";

function Source({ id }: { id: DevelopmentSourceId }) {
  const source = developmentSources.find((item) => item.id === id)!;
  return (
    <div className={s.source}>
      <div>
        <Code2 size={16} />
        <span>
          {source.path} · L{source.start}–{source.end}
        </span>
      </div>
      <pre tabIndex={0} aria-label="Mapping implementation source">
        <code>{source.code}</code>
      </pre>
      <a href={source.url} target="_blank" rel="noreferrer">
        Open pinned implementation <ExternalLink size={13} />
      </a>
    </div>
  );
}
function Scenario({ mapping }: { mapping: Mapping }) {
  const [answer, setAnswer] = useState<number | null>(null);
  const [checked, setChecked] = useState(false);
  return (
    <fieldset className={s.scenario}>
      <legend>Try the contract on a new situation</legend>
      <h3>{mapping.question}</h3>
      {mapping.options.map((option, index) => (
        <label key={option}>
          <input
            type="radio"
            name={`mapping-${mapping.id}`}
            checked={answer === index}
            onChange={() => {
              setAnswer(index);
              setChecked(false);
            }}
          />
          {option}
        </label>
      ))}
      <button
        className={s.primary}
        disabled={answer === null}
        onClick={() => setChecked(true)}
      >
        Check this interpretation <Check size={15} />
      </button>
      {checked && (
        <div className={s.feedback} role="status">
          <strong>
            {answer === mapping.correct
              ? "The contract supports that interpretation."
              : "Revisit what the interface promises."}
          </strong>
          <p>{mapping.explanation}</p>
        </div>
      )}
    </fieldset>
  );
}
function MappingDetail({ mapping }: { mapping: Mapping }) {
  const [field, setField] = useState(0);
  const [source, setSource] = useState(mapping.sources[0].id);
  const item = mapping.fields[field];
  return (
    <div className={s.detail}>
      <div className={s.detailHeading}>
        <span className={s.eyebrow}>{mapping.category}</span>
        <h3>{mapping.title}</h3>
        <p>{mapping.lesson}</p>
      </div>
      <div className={s.fields} role="group" aria-label="Mapping dimensions">
        {mapping.fields.map((f, i) => (
          <button
            key={f.label}
            aria-pressed={field === i}
            onClick={() => setField(i)}
          >
            {f.label}
          </button>
        ))}
      </div>
      <div className={s.mappingGrid} aria-label={`${item.label} mapping`}>
        <article>
          <span className={s.eyebrow}>01 · Native API / driver</span>
          <h4>{mapping.native}</h4>
          <p>{item.native}</p>
        </article>
        <div className={s.arrow}>
          <ArrowRight size={20} />
        </div>
        <article className={s.adapter}>
          <span className={s.eyebrow}>02 · Connector adapter</span>
          <h4>{mapping.wrapper}</h4>
          <p>{item.adapter}</p>
        </article>
        <div className={s.arrow}>
          <ArrowRight size={20} />
        </div>
        <article>
          <span className={s.eyebrow}>03 · SiLA Feature</span>
          <h4>{mapping.feature}</h4>
          <p>{item.contract}</p>
        </article>
      </div>
      <div className={s.meaning} aria-live="polite">
        <strong>Why this mapping matters</strong>
        <p>{item.why}</p>
      </div>
      <details className={s.implementation}>
        <summary>Inspect the actual mapping code</summary>
        <p>
          These excerpts show the connector’s calls and conversions, not the
          vendor SDK implementation itself.
        </p>
        <div
          className={s.fields}
          role="group"
          aria-label="Implementation excerpts"
        >
          {mapping.sources.map((ref) => (
            <button
              key={ref.id}
              aria-pressed={source === ref.id}
              onClick={() => setSource(ref.id)}
            >
              {ref.label}
            </button>
          ))}
        </div>
        <Source id={source} />
      </details>
      <Scenario mapping={mapping} />
    </div>
  );
}
export function CapabilityMap({ onBuild }: { onBuild: () => void }) {
  const [selected, setSelected] = useState(mappings[0].id);
  const current = mappings.find((m) => m.id === selected)!;
  return (
    <section className={s.developer}>
      <header className={s.heading}>
        <span className={s.eyebrow}>
          DEVELOPER VIEW / FROM NATIVE CAPABILITY TO PUBLIC CONTRACT
        </span>
        <h2>API ↔ SiLA mapping</h2>
        <p>
          Pick a capability and compare its native inputs, adapter logic and
          client-facing meaning. The examples come from the pinned Flex
          connector.
        </p>
      </header>
      <div className={s.direction}>
        <ArrowLeftRight size={22} />
        <div>
          <strong>Two directions, one boundary</strong>
          <p>
            Design a mapping from the device capability to the Feature contract.
            At runtime, a client request travels SiLA → adapter → device;
            results and errors travel back.
          </p>
        </div>
      </div>
      <nav className={s.capabilities} aria-label="Capabilities to compare">
        {mappings.map((m) => (
          <button
            key={m.id}
            aria-pressed={selected === m.id}
            onClick={() => setSelected(m.id)}
          >
            <strong>{m.title}</strong>
            <small>{m.category}</small>
          </button>
        ))}
      </nav>
      <MappingDetail key={current.id} mapping={current} />
      <aside className={s.reference}>
        <p>
          <strong>What is shared across devices?</strong> SiLA defines how
          Features expose Commands, Properties and their contracts. The
          identifiers in this example are custom Features from this repository;
          another SiLA device is not automatically compatible with every one of
          them.
        </p>
        <a
          href="https://sila-standard.com/wp-content/uploads/2022/03/SiLA-2-Part-A-Overview-Concepts-and-Core-Specification-v1.1.pdf"
          target="_blank"
          rel="noreferrer"
        >
          SiLA concepts and Feature specification <ExternalLink size={13} />
        </a>
      </aside>
      <button className={s.primary} onClick={onBuild}>
        See the development sequence <ArrowRight size={16} />
      </button>
    </section>
  );
}
const interfaces = [
  {
    id: "sdk",
    title: "Python SDK",
    label: "The Flex example",
    start: "SDK function / object",
    middle: "Python I/O controller",
    detail:
      "An SDK is a library that exposes an API. The pinned Flex motion controller calls the low-level OT3API directly; it does not submit an HTTP job for each aspiration.",
    packets: [
      "Call a native method",
      "Await or observe its documented outcome",
      "Convert the result or exception",
    ],
    question:
      "Check native types, units, backend version and concurrency behavior.",
  },
  {
    id: "http",
    title: "HTTP API",
    label: "Generic design pattern",
    start: "HTTP endpoint / job status",
    middle: "HTTP client adapter",
    detail:
      "Some instruments expose a network API; an SDK may wrap that same API. If a request returns a job ID, accepting the request and finishing the job are different events.",
    packets: [
      "Submit a request; retain its identity",
      "Observe the vendor job until a defined outcome",
      "Map progress, result or uncertainty",
    ],
    question:
      "Check authentication, request identity, status lookup, deadlines and whether retrying can repeat an action.",
  },
  {
    id: "protocol",
    title: "Device protocol",
    label: "Generic design pattern",
    start: "Serial / TCP messages",
    middle: "Driver + I/O controller",
    detail:
      "A documented message protocol can be wrapped even without a high-level SDK. The driver handles framing and parsing; the controller defines the lab operation and its outcome.",
    packets: [
      "Encode a documented device command",
      "Parse acknowledgement and device state",
      "Map the documented outcome, not just received bytes",
    ],
    question:
      "Check message framing, units, synchronization and device-specific stop/readback behavior.",
  },
] as const;
function NativeInterface() {
  const [selected, setSelected] = useState(0);
  const [packet, setPacket] = useState(0);
  const item = interfaces[selected];
  return (
    <section className={s.interface} aria-label="Native interface choices">
      <div className={s.fields} role="group" aria-label="Device interface type">
        {interfaces.map((item, i) => (
          <button
            key={item.id}
            aria-pressed={selected === i}
            onClick={() => {
              setSelected(i);
              setPacket(0);
            }}
          >
            {item.title}
          </button>
        ))}
      </div>
      <span className={s.eyebrow}>{item.label}</span>
      <p>{item.detail}</p>
      <div className={s.transport}>
        <span>{item.start}</span>
        <ArrowRight size={18} />
        <span>{item.middle}</span>
        <ArrowRight size={18} />
        <strong>SiLA Feature</strong>
      </div>
      <div className={s.packet} aria-live="polite">
        <span>{packet + 1} / 3</span>
        <strong>{item.packets[packet]}</strong>
      </div>
      <button
        className={s.secondary}
        disabled={packet === 2}
        onClick={() => setPacket((n) => n + 1)}
      >
        Follow the next boundary <ArrowRight size={14} />
      </button>
      <button
        className={s.linkButton}
        disabled={packet === 0}
        onClick={() => setPacket(0)}
      >
        Restart trace
      </button>
      <p className={s.note}>{item.question}</p>
      <small>
        Illustrated interface patterns; these controls do not connect to a
        device or send network requests.
      </small>
    </section>
  );
}
export function DevelopmentPath({ onMapping }: { onMapping: () => void }) {
  const [stage, setStage] = useState(0);
  const step = developmentSteps[stage];
  const [decision, setDecision] = useState("");
  return (
    <section className={s.developer}>
      <header className={s.heading}>
        <span className={s.eyebrow}>
          DEVELOPER VIEW / BUILD ONE CAPABILITY END TO END
        </span>
        <h2>Build a connector</h2>
        <p>
          Work from the native interface to a clear contract, then through
          implementation and evidence. Each step produces something another
          developer can inspect.
        </p>
      </header>
      <NativeInterface />
      <nav className={s.sequence} aria-label="Connector development steps">
        {developmentSteps.map((item, i) => (
          <button
            key={item.title}
            aria-current={stage === i ? "step" : undefined}
            onClick={() => setStage(i)}
          >
            <span>0{i + 1}</span>
            <strong>{item.title}</strong>
            {i < developmentSteps.length - 1 && <ArrowRight size={15} />}
          </button>
        ))}
      </nav>
      <div className={s.stage} aria-live="polite">
        <div className={s.stageIntro}>
          <span className={s.eyebrow}>STEP {stage + 1} OF 6</span>
          <h3>{step.question}</h3>
          <div className={s.artifact}>
            <Code2 size={25} />
            <span>Produce this</span>
            <strong>{step.artifact}</strong>
          </div>
        </div>
        <div className={s.stageWork}>
          <ol>
            {step.items.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ol>
          <div className={s.evidence}>
            <span className={s.eyebrow}>
              WHERE TO LOOK IN THE FLEX CONNECTOR
            </span>
            <p>{step.evidence}</p>
            <a
              href={`${sourceUrl(step.path)}#L${step.anchor}`}
              target="_blank"
              rel="noreferrer"
            >
              {step.path} <ExternalLink size={13} />
            </a>
          </div>
          <div className={s.meaning}>
            <strong>Check before moving on</strong>
            <p>{step.check}</p>
          </div>
        </div>
      </div>
      <div className={s.stageActions}>
        <button
          className={s.secondary}
          disabled={stage === 0}
          onClick={() => setStage((n) => n - 1)}
        >
          Previous development step
        </button>
        <button
          className={s.primary}
          disabled={stage === 5}
          onClick={() => setStage((n) => n + 1)}
        >
          Next development step <ArrowRight size={15} />
        </button>
      </div>
      <section className={s.recipe}>
        <div>
          <span className={s.eyebrow}>DESIGN EXERCISE</span>
          <h3>Expose a temperature reading.</h3>
          <p>
            The device already reports its temperature. You want a client to
            follow changes, without starting any heating operation.
          </p>
        </div>
        <fieldset>
          <legend>Which contract best matches that requirement?</legend>
          {[
            ["command", "A command that sets a target"],
            ["property", "An observable Property that reports state"],
          ].map(([value, label]) => (
            <label key={value}>
              <input
                type="radio"
                name="feature-design"
                checked={decision === value}
                onChange={() => setDecision(value)}
              />
              {label}
            </label>
          ))}
          {decision && (
            <p className={s.feedback} role="status">
              {decision === "property"
                ? "Yes. Expose reported state as a Property; decide separately whether the client can command a target."
                : "Setting a target changes the device. This requirement is to observe its reported state."}
            </p>
          )}
        </fieldset>
      </section>
      <div className={s.references}>
        <a
          href={sourceUrl("tests/io/test_temperature_module.py")}
          target="_blank"
          rel="noreferrer"
        >
          Adapter tests <ExternalLink size={13} />
        </a>
        <a
          href={sourceUrl("tests/features/test_flex_feature_definitions.py")}
          target="_blank"
          rel="noreferrer"
        >
          Feature definitions <ExternalLink size={13} />
        </a>
        <a
          href={sourceUrl("tests/integration/test_grpc_temperature_module.py")}
          target="_blank"
          rel="noreferrer"
        >
          SiLA client tests <ExternalLink size={13} />
        </a>
        <a
          href={sourceUrl(
            "tests/integration/hardware/test_hitl_temperature_module.py",
          )}
          target="_blank"
          rel="noreferrer"
        >
          Hardware acceptance source <ExternalLink size={13} />
        </a>
      </div>
      <p className={s.note}>
        Browsing the steps is learning progress, not a test result or
        commissioning record. This Academy page does not generate or install a
        connector.
      </p>
      <button className={s.secondary} onClick={onMapping}>
        Return to API ↔ SiLA mapping <ArrowDown size={15} />
      </button>
    </section>
  );
}
