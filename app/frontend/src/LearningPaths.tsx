import { ArrowRight } from "lucide-react";
import { FirstLessonCard } from "./FirstLessonCard";
import { firstTransfer } from "./learningContent";
import {
  LEARNING_LEVELS,
  latestCourseSession,
  learningStatus,
  type LearningLevel,
} from "./learningLevels";
import type { Course, Session } from "./types";
import s from "./LearningPaths.module.css";

type Props = {
  level: LearningLevel;
  courses: Course[];
  sessions: Session[];
  busy: boolean;
  onNavigate: (target: string) => void;
  onFirstLesson: () => void;
  onPractice: () => void;
  onDesign: () => void;
};

function Resource({
  number,
  title,
  description,
  action,
  onOpen,
  disabled,
  status,
}: {
  number: string;
  title: string;
  description: string;
  action: string;
  onOpen: () => void;
  disabled?: boolean;
  status?: string;
}) {
  return (
    <article className={s.resource}>
      <span className={s.number} aria-hidden="true">
        {number}
      </span>
      <div>
        <h3>{title}</h3>
        <p>{description}</p>
        {status && <span className={s.status}>{status}</span>}
      </div>
      <button onClick={onOpen} disabled={disabled}>
        {action} <ArrowRight size={17} />
      </button>
    </article>
  );
}

export default function LearningPaths({
  level,
  courses,
  sessions,
  busy,
  onNavigate,
  onFirstLesson,
  onPractice,
  onDesign,
}: Props) {
  const selected = LEARNING_LEVELS.find((item) => item.id === level)!;
  const first = latestCourseSession(sessions, "flex-first-transfer");
  const practice = latestCourseSession(sessions, "flex-foundations");
  const design = latestCourseSession(sessions, "workflow-sandbox");
  const complete =
    !!first?.lesson_outcome?.practice_completed &&
    !!first?.lesson_outcome?.understanding_demonstrated;
  return (
    <div className={s.page}>
      <header className={s.header}>
        <h1>Learning lab</h1>
        <p>Choose the level that fits your work. You can start at any level.</p>
      </header>
      <nav className={s.levels} aria-label="Learning levels">
        {LEARNING_LEVELS.map((item) => (
          <a
            key={item.id}
            href={`/#/learn/${item.id}`}
            aria-current={level === item.id ? "page" : undefined}
            onClick={(event) => {
              if (
                event.metaKey ||
                event.ctrlKey ||
                event.shiftKey ||
                event.altKey
              )
                return;
              event.preventDefault();
              onNavigate(`learn/${item.id}`);
            }}
          >
            {item.title}
          </a>
        ))}
      </nav>
      <section aria-labelledby="learning-level-title">
        <div className={s.levelHeading}>
          <h2 id="learning-level-title">{selected.heading}</h2>
          <p>{selected.goal}</p>
        </div>
        {level === "beginner" ? (
          <>
            <p className={s.scope}>
              Complete this path without connectors, orchestration or a GPU.
            </p>
            <Resource
              number="01"
              title="Meet the instruments"
              description="Explore Flex and OT-2, read the deck and recognize each pipetting operation."
              action="Explore the instruments"
              onOpen={() => onNavigate("instruments")}
            />
            <div className={s.lesson}>
              <span className={s.number} aria-hidden="true">
                02
              </span>
              <div>
                <FirstLessonCard
                  onStart={onFirstLesson}
                  resume={!!first}
                  disabled={busy}
                />
                <p className={s.status}>{learningStatus(first)}</p>
              </div>
            </div>
            <Resource
              number="03"
              title="Change a simple workflow"
              description="Arrange the deck and change transfer volumes in the existing Flex Foundations exercise."
              action={practice ? "Continue experiment" : "Start an experiment"}
              onOpen={onPractice}
              disabled={busy}
              status={learningStatus(practice)}
            />
            <Resource
              number="04"
              title="Make your own transfer"
              description="Continue your saved workflow or start with a four-step Flex transfer. Edit its slots, volume and destination, then inspect the teaching observations."
              action={design ? "Continue my workflow" : "Open transfer starter"}
              onOpen={onDesign}
              disabled={busy}
              status={learningStatus(design)}
            />
            <details className={s.code}>
              <summary>Read the code behind a 100 µL teaching transfer</summary>
              <p>
                This is the Academy teaching runner’s /sessions request, not an
                Opentrons hardware protocol. The layout names deck slots; each
                action names a well and volume.
              </p>
              <ol>
                <li>
                  <code>pickup</code>: attach a fresh tip.
                </li>
                <li>
                  <code>aspirate</code>: draw 100 µL from stock into the tip.
                </li>
                <li>
                  <code>dispense</code>: release 100 µL into well A1.
                </li>
                <li>
                  <code>drop</code>: discard the used tip.
                </li>
              </ol>
              <pre>
                <code>{JSON.stringify(firstTransfer(), null, 2)}</code>
              </pre>
            </details>
            <aside className={s.finish}>
              <h3>
                {complete
                  ? "Your first transfer is understood."
                  : "Finish by explaining the result."}
              </h3>
              <p>
                Use the lesson’s observations and reflection to explain where
                the liquid went. A saved teaching result records practice; it
                does not qualify you to operate a physical instrument.
              </p>
              <button onClick={onFirstLesson} disabled={busy}>
                {complete
                  ? "Review lesson outcome"
                  : first
                    ? "Return to my lesson"
                    : "Open the first lesson"}
                <ArrowRight size={17} />
              </button>
            </aside>
          </>
        ) : level === "intermediate" ? (
          <>
            <Resource
              number="01"
              title={
                courses.find((course) => course.id === "workflow-readiness")
                  ?.title ?? "Can this workflow run?"
              }
              description="Review and repair a teaching plan, reconcile an uncertain outcome and explain your decision. Existing course answers are kept."
              action="Open workflow judgment course"
              onOpen={() => onNavigate("workflow-course")}
            />
            <Resource
              number="02"
              title="Discovery studio"
              description="Define what changes, what stays fixed and how measurements inform the next experiment."
              action="Open discovery studio"
              onOpen={() => onNavigate("discovery")}
            />
            <Resource
              number="03"
              title="Plan a multi-device workcell"
              description="Assign operations to selected instruments, arrange a bench layout and inspect its synthetic geometry checks."
              action="Open workcell planner"
              onOpen={() => onNavigate("instruments/layout")}
            />
          </>
        ) : (
          <>
            <Resource
              number="01"
              title="Inside a connector"
              description="Explore the existing connector modules, command mapping and referenced implementation."
              action="Open connector explorer"
              onOpen={() => onNavigate("connector")}
            />
            <Resource
              number="02"
              title="Mock command contracts"
              description="Inspect the selected instruments’ mock interfaces and SiLA bundle exports in the workcell planner."
              action="Explore mock connectors"
              onOpen={() => onNavigate("instruments/connectors")}
            />
            <Resource
              number="03"
              title="Device readiness"
              description="Understand the checks required before a real connector can be used. Choosing this level does not grant execution permission."
              action="Review readiness"
              onOpen={() => onNavigate("readiness")}
            />
            <article className={s.planned}>
              <h3>Orchestration</h3>
              <p>
                Planned course. No orchestration lesson or completion assessment
                is available yet.
              </p>
            </article>
          </>
        )}
      </section>
      <section className={s.shared} aria-label="Shared learning resources">
        <h2>Explore alongside any level</h2>
        <button onClick={() => onNavigate("marketplace")}>
          Workflow marketplace <ArrowRight size={17} />
        </button>
        <button onClick={() => onNavigate("sim")}>
          Simulation lab <ArrowRight size={17} />
        </button>
        <button onClick={() => onNavigate("history")}>
          My experiments <ArrowRight size={17} />
        </button>
        <p>
          Native simulation availability depends on the runtime’s readiness, not
          your learning level.
        </p>
      </section>
    </div>
  );
}
