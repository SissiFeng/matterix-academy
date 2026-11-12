import { useRef, useState } from "react";
import { Sparkles } from "lucide-react";
import type { Constraint, Layout, Refinement } from "./instrumentTypes";
import studio from "./InstrumentStudio.module.css";
import s from "./LayoutPanel.module.css";

/** Ask for a change to the layout in plain words; the result lands on the draft. */
export default function LayoutRefine({
  layout,
  constraints,
  onRefine,
  onApply,
  onConstraints,
  busy,
}: {
  /** The draft the request is about; an answer to an older draft is not applied. */
  layout: Layout;
  constraints: Constraint[];
  onRefine: (text: string) => Promise<Refinement>;
  onApply: (next: Layout) => void;
  /** Saves the preferences the request asked for, once the learner agrees. */
  onConstraints: (next: Constraint[]) => void;
  busy: boolean;
}) {
  const current = useRef("");
  current.current = JSON.stringify(layout);
  const [text, setText] = useState("");
  const [asking, setAsking] = useState(false);
  const [result, setResult] = useState<Refinement | null>(null);
  const [error, setError] = useState("");
  const missed = result
    ? [...result.skipped, result.unclear].filter(Boolean)
    : [];
  return (
    <form
      className={s.refine}
      onSubmit={async (e) => {
        e.preventDefault();
        setAsking(true);
        setError("");
        setResult(null);
        const asked = current.current;
        try {
          const next = await onRefine(text.trim());
          if (current.current !== asked) {
            setError("The layout changed while this was read. Ask again.");
            return;
          }
          setResult(next);
          if (next.applied.length) {
            onApply({ bench: next.bench, placements: next.placements });
            setText("");
          }
        } catch (e) {
          setError((e as Error).message);
        } finally {
          setAsking(false);
        }
      }}
    >
      <label>
        Change this layout
        <input
          value={text}
          maxLength={600}
          disabled={asking}
          placeholder="Reader on the left, closer to the Flex; keep the arm where it is"
          onChange={(e) => setText(e.target.value)}
        />
      </label>
      <button
        className={studio.secondary}
        disabled={busy || asking || !text.trim()}
      >
        <Sparkles size={15} aria-hidden /> {asking ? "Reading…" : "Refine"}
      </button>
      {error && <p role="alert">{error}</p>}
      {result && (
        <div className={s.refined} role="status">
          {result.applied.length ? (
            <ul>
              {result.applied.map((line, i) => (
                <li key={i}>{line}</li>
              ))}
            </ul>
          ) : (
            <p>Nothing in that request changes the layout.</p>
          )}
          {missed.length > 0 && <p>Not applied: {missed.join("; ")}</p>}
          {result.search &&
            (JSON.stringify(result.constraints) ===
            JSON.stringify(constraints) ? (
              <p>Search layouts to place the instruments this way.</p>
            ) : (
              <button
                type="button"
                className={studio.secondary}
                disabled={busy}
                onClick={() => onConstraints(result.constraints)}
              >
                Save these preferences
              </button>
            ))}
        </div>
      )}
    </form>
  );
}
