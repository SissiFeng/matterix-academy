import { useEffect, useRef, useState } from "react";
import { Square, Wand2 } from "lucide-react";
import type {
  Layout,
  LayoutCandidate,
  LayoutMetrics,
  LayoutSearchChunk,
  Placement,
} from "./instrumentTypes";
import studio from "./InstrumentStudio.module.css";
import s from "./LayoutPanel.module.css";

/** Stop asking for more once this many layouts are on the list. */
const LIMIT = 60;
const SHOWN = 6;

type Key = keyof Omit<LayoutMetrics, "arm_s">;
const METRICS: {
  key: Key;
  label: string;
  better: "low" | "high";
  show: (v: number) => string;
}[] = [
  {
    key: "run_s",
    label: "Run time",
    better: "low",
    show: (v) => `${v.toFixed(1)} s run`,
  },
  {
    key: "path_m",
    label: "Arm path",
    better: "low",
    show: (v) => `${v.toFixed(2)} m path`,
  },
  {
    key: "clearance_m",
    label: "Clearance",
    better: "high",
    show: (v) => `${(v * 100).toFixed(1)} cm clearance`,
  },
  {
    key: "reach_margin_m",
    label: "Reach margin",
    better: "high",
    show: (v) => `${(v * 100).toFixed(0)} cm reach margin`,
  },
  {
    key: "area_m2",
    label: "Bench area",
    better: "low",
    show: (v) => `${v.toFixed(2)} m² bench`,
  },
];
const cost = (c: LayoutMetrics, key: Key) =>
  METRICS.find((m) => m.key === key)!.better === "low" ? c[key] : -c[key];

/** No other layout is at least as good on every metric and better on one. */
export function tradeOffs<T extends LayoutMetrics>(all: T[]) {
  return all.filter(
    (a) =>
      !all.some(
        (b) =>
          b !== a &&
          METRICS.every((m) => cost(b, m.key) <= cost(a, m.key)) &&
          METRICS.some((m) => cost(b, m.key) < cost(a, m.key)),
      ),
  );
}

const sameLayout = (a: Layout, b: Layout) =>
  JSON.stringify(a.placements) === JSON.stringify(b.placements);

export default function LayoutOptions({
  layout,
  onApply,
  onSearch,
}: {
  layout: Layout;
  onApply: (next: Layout) => void;
  onSearch: (
    fixed: Placement[],
    start: number,
    avoid: Placement[][],
  ) => Promise<LayoutSearchChunk>;
}) {
  const kept = layout.placements.filter((p) => p.kept);
  const [aroundKept, setAroundKept] = useState(true);
  const fixed = aroundKept ? kept : [];
  const [found, setFound] = useState<LayoutCandidate[]>([]);
  const [progress, setProgress] = useState<{
    done: number;
    total: number;
  } | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [running, setRunning] = useState(false);
  const [sortBy, setSortBy] = useState<Key>("run_s");
  const [onlyBest, setOnlyBest] = useState(true);
  const [all, setAll] = useState(false);
  const runId = useRef(0);

  // Results answer one bench and one set of kept instruments.
  const inputs = JSON.stringify([layout.bench, fixed]);
  useEffect(() => {
    runId.current += 1;
    setFound([]);
    setProgress(null);
    setFailure(null);
    setRunning(false);
  }, [inputs]);

  const search = async () => {
    const id = ++runId.current;
    setRunning(true);
    setError("");
    setFailure(null);
    let all: LayoutCandidate[] = [];
    let start: number | null = 0;
    setFound([]);
    try {
      while (start !== null && runId.current === id && all.length < LIMIT) {
        const chunk = await onSearch(
          fixed,
          start,
          all.map((c) => c.layout.placements),
        );
        if (runId.current !== id) return;
        all = [...all, ...chunk.candidates];
        setFound(all);
        setFailure(chunk.failure);
        setProgress({ done: chunk.next ?? chunk.total, total: chunk.total });
        start = chunk.next;
      }
    } catch (e) {
      if (runId.current === id) setError((e as Error).message);
    } finally {
      if (runId.current === id) setRunning(false);
    }
  };

  const numbered = found.map((c, i) => ({ ...c, n: i + 1 }));
  const listed = (onlyBest ? tradeOffs(numbered) : numbered).sort(
    (a, b) => cost(a, sortBy) - cost(b, sortBy) || a.n - b.n,
  );
  const shown = all ? listed : listed.slice(0, SHOWN);

  return (
    <div className={s.options} aria-live="polite">
      <div className={s.optionBar}>
        <div className={s.scope} role="radiogroup" aria-label="Search scope">
          <label>
            <input
              type="radio"
              checked={!aroundKept || !kept.length}
              onChange={() => setAroundKept(false)}
            />
            Whole bench
          </label>
          <label
            title={kept.length ? undefined : "Mark instruments to keep first"}
          >
            <input
              type="radio"
              checked={aroundKept && kept.length > 0}
              disabled={!kept.length}
              onChange={() => setAroundKept(true)}
            />
            Around {kept.length} kept
          </label>
        </div>
        {running ? (
          <button
            className={studio.secondary}
            onClick={() => {
              runId.current += 1;
              setRunning(false);
            }}
          >
            <Square size={12} /> Stop
          </button>
        ) : (
          <button className={studio.secondary} onClick={search}>
            <Wand2 size={14} />{" "}
            {found.length ? "Search again" : "Search layouts"}
          </button>
        )}
      </div>
      {progress && (
        <small className={s.hint}>
          {running ? "Searching · " : ""}
          {found.length} layout{found.length === 1 ? "" : "s"} from{" "}
          {progress.done} of {progress.total} starting arrangements
        </small>
      )}
      {error && (
        <p className={s.problem} role="status">
          {error}
        </p>
      )}
      {!running && progress && !found.length && failure && (
        <p className={s.problem} role="status">
          No feasible layout. {failure}
        </p>
      )}
      {found.length > 0 && (
        <>
          <div className={s.optionControls}>
            <label>
              Sort by
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value as Key)}
              >
                {METRICS.map((m) => (
                  <option key={m.key} value={m.key}>
                    {m.label}
                  </option>
                ))}
              </select>
            </label>
            <label className={s.inlineCheck}>
              <input
                type="checkbox"
                checked={onlyBest}
                onChange={(e) => setOnlyBest(e.target.checked)}
              />
              Best trade-offs only
            </label>
          </div>
          <ol className={s.optionList}>
            {shown.map((c) => (
              <li key={c.n}>
                <button
                  className={`${s.motion} ${sameLayout(c.layout, layout) ? s.motionActive : ""}`}
                  aria-pressed={sameLayout(c.layout, layout)}
                  onClick={() => onApply(c.layout)}
                >
                  <span>Layout {c.n}</span>
                  <small>
                    {METRICS.map((m) => (
                      <span
                        key={m.key}
                        className={m.key === sortBy ? s.sorted : ""}
                      >
                        {m.show(c[m.key])}
                      </span>
                    ))}
                  </small>
                </button>
              </li>
            ))}
          </ol>
          {listed.length > SHOWN && (
            <button className={s.more} onClick={() => setAll(!all)}>
              {all ? `Show top ${SHOWN}` : `Show all ${listed.length}`}
            </button>
          )}
        </>
      )}
    </div>
  );
}
