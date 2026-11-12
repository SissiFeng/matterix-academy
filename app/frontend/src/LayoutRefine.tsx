import { useState } from "react";
import { Sparkles } from "lucide-react";
import type { Refinement } from "./instrumentTypes";
import studio from "./InstrumentStudio.module.css";
import s from "./LayoutPanel.module.css";

/** Ask for a change to the layout in plain words; the result lands on the draft. */
export default function LayoutRefine({
  onRefine,
  onApply,
  busy,
}: {
  onRefine: (text: string) => Promise<Refinement>;
  onApply: (result: Refinement) => void;
  busy: boolean;
}) {
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
        try {
          const next = await onRefine(text.trim());
          setResult(next);
          if (next.applied.length) {
            onApply(next);
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
              {result.applied.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          ) : (
            <p>Nothing in that request changes the layout.</p>
          )}
          {missed.length > 0 && <p>Not applied: {missed.join("; ")}</p>}
          {result.search && (
            <p>Search layouts to place the instruments by these preferences.</p>
          )}
        </div>
      )}
    </form>
  );
}
