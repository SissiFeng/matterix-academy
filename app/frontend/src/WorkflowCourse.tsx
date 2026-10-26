import { useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, CheckCircle2, FileSearch } from "lucide-react";
import { api, json } from "./api";
import type { Assessment, Session } from "./types";
import s from "./WorkflowCourse.module.css";

type Progress = {
  version: number;
  evidence: "synthetic";
  phase: "review" | "repair" | "practice" | "incident" | "reflect" | "complete";
  findings: string[];
  plan: { source_volume: number; mixing: "command" | "ideal" };
  trial: {
    evidence: "synthetic";
    steps: number;
    assessment: Assessment;
    state: Session["state"];
    events: Session["events"];
  } | null;
  recovery: string;
  reconciled: boolean;
  decision: string;
  rationale: string;
  completed: boolean;
  feedback: string;
};
const stages = [
  "Review",
  "Repair",
  "Practice",
  "Reconcile",
  "Conclude",
  "Complete",
];
const phaseIds = [
  "review",
  "repair",
  "practice",
  "incident",
  "reflect",
  "complete",
];
const findings = [
  ["source", "The source cannot supply the first 100 µL transfer"],
  [
    "mixing",
    "An explicit mixing command is unsupported by this teaching runner",
  ],
  ["physical", "A teaching pass does not authorize a physical run"],
  ["tips", "Three fresh tips are insufficient for three transfers"],
  ["capacity", "A 100 µL aspiration exceeds the 300 µL teaching limit"],
];

export default function WorkflowCourse({
  onBack,
  registerLeaveGuard,
}: {
  onBack: () => void;
  registerLeaveGuard: (guard: (() => boolean) | null) => void;
}) {
  const [progress, setProgress] = useState<Progress | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [source, setSource] = useState("50");
  const [mixing, setMixing] = useState("command");
  const [recovery, setRecovery] = useState("");
  const [decision, setDecision] = useState("");
  const [rationale, setRationale] = useState("");
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [blocked, setBlocked] = useState(false);
  const alive = useRef(false);
  const lock = useRef(false);
  const readGeneration = useRef(0);
  const unresolvedVersion = useRef<number | null>(null);

  const accept = (next: Progress) => {
    if (!alive.current) return;
    unresolvedVersion.current = null;
    setProgress(next);
    setSelected(next.findings);
    setSource(String(next.plan.source_volume));
    setMixing(next.plan.mixing);
    setRecovery(next.recovery);
    setDecision(next.decision);
    setRationale(next.rationale);
    setDirty(false);
    setBlocked(false);
  };
  const reconcile = (next: Progress) => {
    if (!alive.current) return;
    const expected = unresolvedVersion.current;
    if (expected !== null && next.version < expected)
      throw new Error(
        "The saved course record is older than the last confirmed version.",
      );
    if (expected !== null && next.version === expected) {
      // No command committed. Keep the draft and its navigation warning intact.
      unresolvedVersion.current = null;
      setProgress(next);
      setBlocked(false);
      setError(
        "No saved change was found. Your answers are still here; review them before saving again.",
      );
    } else accept(next);
  };
  const load = async () => {
    const generation = ++readGeneration.current;
    setBusy(true);
    setError("");
    try {
      const next = await api<Progress>("/workflow-course");
      if (generation === readGeneration.current) reconcile(next);
    } catch (e) {
      if (alive.current && generation === readGeneration.current) {
        setError((e as Error).message);
        setBlocked(true);
      }
    } finally {
      if (alive.current && generation === readGeneration.current)
        setBusy(false);
    }
  };
  useEffect(() => {
    alive.current = true;
    void load();
    return () => {
      alive.current = false;
      readGeneration.current += 1;
    };
    // Load once per mounted learner view; mutations reconcile through this same record.
  }, []);
  useEffect(() => {
    registerLeaveGuard(
      () =>
        !dirty ||
        window.confirm("Your course answers are not saved. Leave this course?"),
    );
    const warn = (event: BeforeUnloadEvent) => {
      if (dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", warn);
    return () => {
      registerLeaveGuard(null);
      window.removeEventListener("beforeunload", warn);
    };
  }, [dirty, registerLeaveGuard]);

  const send = async (action: string, answers: object = {}) => {
    if (!progress || lock.current || blocked) return;
    lock.current = true;
    unresolvedVersion.current = progress.version;
    readGeneration.current += 1;
    setBusy(true);
    setError("");
    try {
      accept(
        await api<Progress>(
          "/workflow-course",
          json({ expected_version: progress.version, action, ...answers }),
        ),
      );
    } catch (e) {
      if (!alive.current) return;
      setError(
        `${(e as Error).message} Your saved course record is being checked; the action will not be replayed.`,
      );
      try {
        reconcile(await api<Progress>("/workflow-course"));
      } catch {
        if (alive.current) {
          setBlocked(true);
          setError(
            "The saved outcome could not be checked. Reload saved progress before continuing. No action has been replayed.",
          );
        }
      }
    } finally {
      lock.current = false;
      if (alive.current) setBusy(false);
    }
  };
  const edit = () => setDirty(true);
  return (
    <article className={s.course}>
      <button className={s.back} onClick={onBack}>
        <ArrowLeft size={16} /> Back to learning lab
      </button>
      <header className={s.header}>
        <span className={s.eyebrow}>15–20 MIN</span>
        <h1>Can this workflow run?</h1>
        <p className={s.boundary}>
          <FileSearch size={18} /> Synthetic teaching only · No Isaac/GPU,
          physical robot or chemical validation. Course completion grants no
          hardware authorization.
        </p>
      </header>
      {error && (
        <div role="alert" className={s.notice}>
          {error}
        </div>
      )}
      {blocked && (
        <button
          className={s.secondary}
          disabled={busy}
          onClick={() => void load()}
        >
          Reload saved progress
        </button>
      )}
      {!progress ? (
        <p role="status">
          {busy ? "Loading saved course…" : "Course progress is unavailable."}
        </p>
      ) : (
        <>
          <ol className={s.stages} aria-label="Course stages">
            {stages.map((label, i) => (
              <li
                key={label}
                aria-current={
                  phaseIds[i] === progress.phase ? "step" : undefined
                }
              >
                <span>{i + 1}</span>
                {label}
              </li>
            ))}
          </ol>
          <div className={s.workspace}>
            <aside className={s.proposal} aria-label="Proposed workflow">
              <span className={s.eyebrow}>AGENT PROPOSAL / NOT APPROVED</span>
              <h2>Three-step serial dilution</h2>
              <p>
                “Transfer 100 µL from stock → A1 → A2 → A3, mix explicitly after
                each dispense, then approve the physical workflow when the
                teaching run passes.”
              </p>
              <dl>
                <div>
                  <dt>Starting stock</dt>
                  <dd>50 µL at 100%</dd>
                </div>
                <div>
                  <dt>Diluent</dt>
                  <dd>100 µL in each target well</dd>
                </div>
                <div>
                  <dt>Resources</dt>
                  <dd>Three fresh tips; 300 µL teaching capacity</dd>
                </div>
                <div>
                  <dt>Supported actions</dt>
                  <dd>Pick up, aspirate, dispense, discard</dd>
                </div>
                <div>
                  <dt>Model</dt>
                  <dd>
                    Ideal instantaneous mixing; no explicit mixing command
                  </dd>
                </div>
                <div>
                  <dt>Physical observations</dt>
                  <dd>None. No instrument is connected.</dd>
                </div>
              </dl>
              {progress.phase !== "review" && (
                <div className={s.revised}>
                  <strong>Saved teaching plan</strong>
                  <p>
                    Stock: {progress.plan.source_volume} µL ·{" "}
                    {progress.plan.mixing === "ideal"
                      ? "Ideal-mixing assumption"
                      : "Unsupported mixing command"}
                  </p>
                  <small>
                    Teaching practice only. Physical approval remains
                    unavailable.
                  </small>
                </div>
              )}
            </aside>
            <section className={s.task} aria-label="Current course task">
              <p role="status" className={s.feedback}>
                {progress.feedback}
              </p>
              <fieldset disabled={busy || blocked} className={s.controls}>
                <legend className={s.eyebrow}>
                  {stages[phaseIds.indexOf(progress.phase)]}
                </legend>
                {progress.phase === "review" && (
                  <>
                    <h2>Which claims prevent approval?</h2>
                    <p>
                      Select all three gaps. Use the proposal and resource facts
                      as evidence.
                    </p>
                    {findings.map(([value, label]) => (
                      <label className={s.choice} key={value}>
                        <input
                          type="checkbox"
                          checked={selected.includes(value)}
                          onChange={() => {
                            setSelected(
                              selected.includes(value)
                                ? selected.filter((v) => v !== value)
                                : [...selected, value],
                            );
                            edit();
                          }}
                        />
                        {label}
                      </label>
                    ))}
                    <button
                      className={s.primary}
                      onClick={() =>
                        void send("inspect", { findings: selected })
                      }
                    >
                      Check the gaps <ArrowRight size={16} />
                    </button>
                  </>
                )}
                {progress.phase === "repair" && (
                  <form
                    onSubmit={(event) => {
                      event.preventDefault();
                      void send("repair", {
                        source_volume: Number(source),
                        mixing,
                      });
                    }}
                  >
                    <h2>Repair the teaching plan</h2>
                    <p>
                      The first transfer needs 100 µL of stock. Later transfers
                      draw from the preceding well, with a fresh tip each time.
                    </p>
                    <label>
                      Starting source volume (µL)
                      <input
                        type="number"
                        required
                        min="0"
                        max="1500"
                        step="any"
                        value={source}
                        onChange={(event) => {
                          setSource(event.target.value);
                          edit();
                        }}
                      />
                    </label>
                    <label>
                      Mixing approach
                      <select
                        value={mixing}
                        onChange={(event) => {
                          setMixing(event.target.value);
                          edit();
                        }}
                      >
                        <option value="command">
                          Keep the explicit mixing command
                        </option>
                        <option value="ideal">
                          Use ideal instantaneous mixing as a teaching
                          assumption
                        </option>
                      </select>
                    </label>
                    <button className={s.primary}>
                      Save repaired plan <ArrowRight size={16} />
                    </button>
                  </form>
                )}
                {progress.phase === "practice" && (
                  <>
                    <h2>Test the repaired plan</h2>
                    <p>
                      Run 12 teaching actions. The target concentrations are
                      50%, 25% and 12.5%. The calculator checks volumes,
                      concentration bookkeeping and fresh-tip rules.
                    </p>
                    <p>
                      Geometry, actual mixing, device connectivity and chemistry
                      are not evaluated.
                    </p>
                    <button
                      className={s.primary}
                      onClick={() => void send("practice")}
                    >
                      Run synthetic trial <ArrowRight size={16} />
                    </button>
                  </>
                )}
                {progress.phase === "incident" && (
                  <>
                    <h2>The response is missing. What next?</h2>
                    <p className={s.notice}>
                      Scripted incident, separate from your completed trial: a
                      dispense request with ID <code>demo-dispense-03</code> was
                      sent, then the connection dropped before its response
                      arrived. Its outcome is unknown.
                    </p>
                    <p>
                      This is a fictional command record. Choosing an answer
                      sends no device request.
                    </p>
                    {[
                      ["retry", "Immediately resend the dispense command"],
                      [
                        "assume",
                        "Mark the command successful because it was sent",
                      ],
                      [
                        "read",
                        "Read the original command record without replaying it",
                      ],
                    ].map(([value, label]) => (
                      <label className={s.choice} key={value}>
                        <input
                          type="radio"
                          name="recovery"
                          checked={recovery === value}
                          onChange={() => {
                            setRecovery(value);
                            edit();
                          }}
                        />
                        {label}
                      </label>
                    ))}
                    <button
                      className={s.primary}
                      disabled={!recovery}
                      onClick={() => void send("reconcile", { recovery })}
                    >
                      Check recovery decision
                    </button>
                  </>
                )}
                {progress.phase === "reflect" && (
                  <form
                    onSubmit={(event) => {
                      event.preventDefault();
                      void send("assess", { decision, rationale });
                    }}
                  >
                    <h2>What can you conclude?</h2>
                    <p>
                      The fictional record confirms one completed dispense. Your
                      teaching trial passed. No physical observations were
                      collected.
                    </p>
                    {[
                      [
                        "hardware",
                        "The physical workflow is qualified and may run",
                      ],
                      [
                        "synthetic",
                        "The repaired plan passed synthetic checks; physical readiness is unverified",
                      ],
                      [
                        "failed",
                        "The timeout proves the dispense never happened",
                      ],
                    ].map(([value, label]) => (
                      <label className={s.choice} key={value}>
                        <input
                          required
                          type="radio"
                          name="decision"
                          checked={decision === value}
                          onChange={() => {
                            setDecision(value);
                            edit();
                          }}
                        />
                        {label}
                      </label>
                    ))}
                    <label>
                      Explain your evidence and its limits
                      <textarea
                        required
                        minLength={20}
                        maxLength={600}
                        rows={5}
                        value={rationale}
                        onChange={(event) => {
                          setRationale(event.target.value);
                          edit();
                        }}
                      />
                    </label>
                    <small>
                      20–600 characters. Your explanation is saved for
                      reflection, not automatically graded for scientific
                      correctness.
                    </small>
                    <button className={s.primary}>Submit conclusion</button>
                  </form>
                )}
                {progress.completed && (
                  <>
                    <CheckCircle2 size={32} />
                    <h2>Workflow judgment complete</h2>
                    <p>
                      You identified the gaps, repaired the plan, tested
                      synthetic behavior and reconciled before retrying.
                    </p>
                    <h3>Your saved explanation</h3>
                    <p className={s.rationale}>{progress.rationale}</p>
                    <p>
                      No physical-device qualification or permission was issued.
                    </p>
                    <button
                      className={s.secondary}
                      onClick={() => {
                        if (
                          window.confirm(
                            "Restart this course and clear its saved answers and trial?",
                          )
                        )
                          void send("restart");
                      }}
                    >
                      Restart course
                    </button>
                  </>
                )}
              </fieldset>
              {progress.trial && (
                <section
                  className={s.results}
                  aria-label="Synthetic trial evidence"
                >
                  <h3>Synthetic trial · {progress.trial.steps} actions</h3>
                  {progress.trial.assessment.checks.map((check) => (
                    <p key={check.label}>
                      <CheckCircle2 size={15} />
                      {check.label}
                    </p>
                  ))}
                  <details>
                    <summary>Inspect synthetic action history</summary>
                    <ol>
                      {progress.trial.events.map((event, i) => (
                        <li key={i}>{event.message}</li>
                      ))}
                    </ol>
                  </details>
                </section>
              )}
            </section>
          </div>
          <footer className={s.footer}>
            {busy
              ? "Saving or calculating…"
              : dirty
                ? "Answers not saved"
                : `Progress saved · revision ${progress.version}`}
            <span>Synthetic evidence only</span>
          </footer>
        </>
      )}
    </article>
  );
}
