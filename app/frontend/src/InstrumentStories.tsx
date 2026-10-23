import { useEffect, useId, useRef, useState } from "react";
import { ArrowUpRight, Check, Pause, Play, RotateCcw } from "lucide-react";
import InstrumentIllustration from "./InstrumentIllustration";
import {
  STORY_DURATION,
  storyCaption,
  storyChapterAt,
  storyChapters,
  storyInstruments,
  storyWorkflows,
  type StoryInstrument,
  type StoryStarter,
  type StoryWorkflow,
} from "./instrumentStoriesContent";
import s from "./InstrumentStories.module.css";

export default function InstrumentStories({
  onDesign,
  busy = false,
  compact = false,
  headingLevel = 2,
}: {
  onDesign: (instrument: StoryInstrument, starter: StoryStarter) => void;
  busy?: boolean;
  compact?: boolean;
  headingLevel?: 1 | 2;
}) {
  const Heading = headingLevel === 1 ? "h1" : "h2";
  const [instrument, setInstrument] = useState<StoryInstrument>("flex");
  const [workflow, setWorkflow] = useState<StoryWorkflow>("transfer");
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(() =>
    typeof window !== "undefined"
      ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
      : false,
  );
  const timeRef = useRef(0);
  const id = useId();
  const chapter = storyChapterAt(time);
  const caption = storyCaption(instrument, workflow, chapter);
  const name = storyInstruments[instrument].shortName;

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const updatePreference = () => {
      setReducedMotion(query.matches);
      if (query.matches) setPlaying(false);
    };
    const pauseWhenHidden = () => {
      if (document.visibilityState === "hidden") setPlaying(false);
    };
    query.addEventListener("change", updatePreference);
    document.addEventListener("visibilitychange", pauseWhenHidden);
    return () => {
      query.removeEventListener("change", updatePreference);
      document.removeEventListener("visibilitychange", pauseWhenHidden);
    };
  }, []);

  useEffect(() => {
    if (!playing || reducedMotion) return;
    let frame = 0;
    let previous: number | null = null;
    const advance = (now: number) => {
      if (document.visibilityState === "hidden") {
        setPlaying(false);
        return;
      }
      if (previous !== null) {
        timeRef.current = Math.min(
          STORY_DURATION,
          timeRef.current + (now - previous) / 1000,
        );
        setTime(timeRef.current);
      }
      previous = now;
      if (timeRef.current >= STORY_DURATION) {
        setPlaying(false);
        return;
      }
      frame = window.requestAnimationFrame(advance);
    };
    frame = window.requestAnimationFrame(advance);
    return () => window.cancelAnimationFrame(frame);
  }, [playing, reducedMotion]);

  function seek(value: number) {
    setPlaying(false);
    timeRef.current = value;
    setTime(value);
  }

  function play() {
    if (reducedMotion) return;
    if (timeRef.current >= STORY_DURATION) {
      timeRef.current = 0;
      setTime(0);
    }
    setPlaying(true);
  }

  function selectInstrument(value: StoryInstrument) {
    seek(0);
    setInstrument(value);
  }

  return (
    <section
      className={`${s.stories} ${compact ? s.compact : ""}`}
      aria-labelledby={`${id}-title`}
      data-testid="instrument-stories"
    >
      <header className={s.header}>
        <div>
          <p className={s.eyebrow}>Two instruments. Your imagination.</p>
          <Heading id={`${id}-title`}>
            See it move.
            <br />
            <span>Then make it yours.</span>
          </Heading>
        </div>
        <p className={s.introduction}>
          Meet the instruments, follow the liquid, then build a workflow of your
          own. No lab experience needed.
        </p>
      </header>

      <div
        className={s.instrumentChoices}
        role="group"
        aria-label="Choose an instrument"
      >
        {(["flex", "ot2"] as const).map((choice) => (
          <button
            key={choice}
            type="button"
            className={`${s.instrumentChoice} ${instrument === choice ? s.selectedInstrument : ""}`}
            aria-label={storyInstruments[choice].name}
            aria-pressed={instrument === choice}
            onClick={() => selectInstrument(choice)}
          >
            <div className={s.miniInstrument} aria-hidden="true">
              <InstrumentIllustration instrument={choice} overview />
            </div>
            <div>
              <span className={s.instrumentName}>
                {storyInstruments[choice].name}
              </span>
              <span className={s.instrumentDescription}>
                {storyInstruments[choice].description}
              </span>
            </div>
            <span className={s.choiceIndicator} aria-hidden="true">
              {instrument === choice ? (
                <Check size={17} />
              ) : (
                <ArrowUpRight size={17} />
              )}
            </span>
          </button>
        ))}
      </div>

      <div className={s.playback}>
        <button
          type="button"
          className={s.playButton}
          onClick={playing ? () => setPlaying(false) : play}
          disabled={reducedMotion}
          aria-label={`${playing ? "Pause" : "Play"} ${name} introduction`}
          title={
            reducedMotion
              ? "Reduced motion is on. Use the chapter buttons to explore."
              : undefined
          }
        >
          {playing ? (
            <Pause size={17} fill="currentColor" />
          ) : (
            <Play size={17} fill="currentColor" />
          )}
          <span>
            {playing
              ? "Pause"
              : time >= STORY_DURATION
                ? "Play again"
                : "Play introduction"}
          </span>
        </button>
        <button
          type="button"
          className={s.replayButton}
          aria-label={`Replay ${name} introduction`}
          onClick={() => {
            seek(0);
            if (!reducedMotion) setPlaying(true);
          }}
        >
          <RotateCcw size={17} />
        </button>
        <label className={s.timeline}>
          <span className={s.srOnly}>Introduction progress</span>
          <input
            type="range"
            min="0"
            max={STORY_DURATION}
            step="0.1"
            value={time}
            onChange={(event) => seek(Number(event.target.value))}
            aria-valuetext={`${Math.floor(time)} of ${STORY_DURATION} seconds, ${storyChapters[chapter].label}`}
          />
        </label>
        <span
          className={s.timestamp}
        >{`0:${String(Math.floor(time)).padStart(2, "0")} / 0:36`}</span>
      </div>
      <div className={s.storyStage}>
        <div className={s.visual}>
          <div className={s.visualTopline}>
            <span className={s.teachingBadge}>
              <span /> Illustrative teaching animation
            </span>
            <span>36 sec · Explore at your pace</span>
          </div>
          <InstrumentIllustration
            instrument={instrument}
            time={time}
            workflow={workflow}
          />
          <div
            className={s.visualLegend}
            role="group"
            aria-label="Illustration legend"
          >
            <span>
              <i className={s.tipColor} /> Disposable tips
            </span>
            <span>
              <i className={s.stockColor} /> Stock
            </span>
            <span>
              <i className={s.sampleColor} />{" "}
              {workflow === "dilution" ? "Buffer + tracer" : "Sample wells"}
            </span>
          </div>
        </div>
        <div className={s.storyText}>
          <div className={s.chapterCount}>
            <span>{String(chapter + 1).padStart(2, "0")}</span>
            <span>/ {String(storyChapters.length).padStart(2, "0")}</span>
          </div>
          <div className={s.caption} aria-live="polite" aria-atomic="true">
            <p className={s.chapterLabel}>{storyChapters[chapter].label}</p>
            <h3>{caption.heading}</h3>
            <p>{caption.body}</p>
          </div>
          <p className={s.captionDetail}>{caption.detail}</p>
          <p className={s.deckGuide}>{storyInstruments[instrument].deck}</p>
        </div>
      </div>

      {reducedMotion && (
        <p className={s.motionNote}>
          Reduced motion is on. Explore the still illustrations using the
          chapters below.
        </p>
      )}
      <div
        className={s.chapters}
        role="group"
        aria-label="Introduction chapters"
      >
        {storyChapters.map((entry, index) => (
          <button
            key={entry.label}
            type="button"
            className={chapter === index ? s.currentChapter : undefined}
            aria-current={chapter === index ? "step" : undefined}
            onClick={() => seek(entry.at)}
          >
            <span>{String(index + 1).padStart(2, "0")}</span>
            {entry.label}
          </button>
        ))}
      </div>

      <div className={s.workflowInvitation}>
        <div className={s.workflowHeading}>
          <p className={s.eyebrow}>From watching to making</p>
          <h3>Where will you start?</h3>
        </div>
        <div
          className={s.workflowChoices}
          role="group"
          aria-label="Choose a starting workflow"
        >
          {(Object.keys(storyWorkflows) as StoryWorkflow[]).map(
            (choice, index) => (
              <button
                key={choice}
                type="button"
                aria-label={storyWorkflows[choice].label}
                aria-pressed={workflow === choice}
                className={workflow === choice ? s.selectedWorkflow : undefined}
                onClick={() => {
                  setWorkflow(choice);
                  seek(20);
                }}
              >
                <WorkflowMark kind={choice} />
                <span>
                  <small>{String(index + 1).padStart(2, "0")}</small>
                  {storyWorkflows[choice].label}
                </span>
                <p>{storyWorkflows[choice].description}</p>
              </button>
            ),
          )}
        </div>
        <div className={s.designActions}>
          <p>Combine steps. Change the volumes. See what happens.</p>
          <div>
            <button
              type="button"
              className={s.primaryButton}
              disabled={busy}
              onClick={() => onDesign(instrument, workflow)}
            >
              {busy ? "Opening studio…" : "Use this workflow"}
              <ArrowUpRight size={19} />
            </button>
            <button
              type="button"
              className={s.blankButton}
              disabled={busy}
              onClick={() => onDesign(instrument, "blank")}
            >
              Start with a blank deck
            </button>
          </div>
        </div>
      </div>
      <p className={s.boundary}>
        Synthetic learning space · Illustrations and liquid models are not live
        instrument footage, Isaac simulation, or validated lab protocols.
      </p>
    </section>
  );
}

function WorkflowMark({ kind }: { kind: StoryWorkflow }) {
  return (
    <svg viewBox="0 0 180 57" aria-hidden="true" className={s.workflowMark}>
      <path
        d="M17 17v24c0 9 24 9 24 0V17"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
      />
      <path d="M20 30v10c0 6 18 6 18 0V30Z" fill="#ce7151" />
      <ellipse
        cx="29"
        cy="17"
        rx="12"
        ry="4"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
      />
      <path
        d="M49 25h22m-5-5 5 5-5 5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
      />
      {(kind === "transfer" ? [105] : [93, 123, 153]).map((x, index) => (
        <g key={x}>
          <path
            d={`M${x - 8} 22v20c0 7 16 7 16 0V22`}
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
          />
          <path
            d={`M${x - 5} 32v9c0 4 10 4 10 0v-9Z`}
            fill={
              kind === "dilution"
                ? ["#b46c91", "#b6a2c0", "#ccc0d4"][index]
                : "#ce7151"
            }
          />
          <ellipse
            cx={x}
            cy="22"
            rx="8"
            ry="3"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
          />
          {kind === "dilution" && index < 2 && (
            <path
              d={`M${x + 10} 16h10m-3-3 3 3-3 3`}
              fill="none"
              stroke="currentColor"
              strokeWidth="1.2"
            />
          )}
        </g>
      ))}
    </svg>
  );
}
