import { useState } from "react";
import { Plus, X } from "lucide-react";
import {
  siteKeys,
  type Constraint,
  type Side,
  type Twin,
} from "./instrumentTypes";
import { isArm } from "./layoutGeometry";
import studio from "./InstrumentStudio.module.css";
import s from "./LayoutPanel.module.css";

type Kind = Constraint["kind"];
const KINDS: { kind: Kind; label: string }[] = [
  { kind: "reach_slots", label: "Arm reaches slots on" },
  { kind: "zone", label: "Keep on one side" },
  { kind: "near", label: "Keep close together" },
  { kind: "apart", label: "Keep apart" },
  { kind: "exclude", label: "Leave off the bench" },
];
const SIDES: Side[] = ["left", "right", "front", "back"];

export function describe(c: Constraint, name: (id: string) => string) {
  const a = name(c.twin_id);
  const b = c.other_id ? name(c.other_id) : "";
  switch (c.kind) {
    case "reach_slots":
      return `Arm reaches ${c.count} slot${c.count === 1 ? "" : "s"} on ${a}`;
    case "zone":
      return `${a} on the ${c.side}`;
    case "near":
      return `${a} within ${c.metres} m of ${b}`;
    case "apart":
      return `${a} at least ${c.metres} m from ${b}`;
    case "exclude":
      return `${a} off the bench`;
  }
}

/** The user's layout preferences; the search honours every one. */
export default function LayoutPreferences({
  twins,
  constraints,
  onSave,
  busy,
}: {
  twins: Twin[];
  constraints: Constraint[];
  onSave: (next: Constraint[]) => void;
  busy: boolean;
}) {
  const stations = twins.filter((t) => !isArm(t));
  const name = (id: string) =>
    twins.find((t) => t.id === id)?.spec?.name ?? "removed instrument";
  const [kind, setKind] = useState<Kind>("reach_slots");
  const pool =
    kind === "reach_slots"
      ? stations.filter((t) => siteKeys(t.spec!).length > 0)
      : kind === "zone" || kind === "exclude"
        ? twins
        : stations;
  const [twinId, setTwinId] = useState("");
  const [otherId, setOtherId] = useState("");
  const [count, setCount] = useState(2);
  const [side, setSide] = useState<Side>("left");
  const [metres, setMetres] = useState(0.6);
  const first = pool.find((t) => t.id === twinId) ?? pool[0];
  const other =
    pool.find((t) => t.id === otherId && t.id !== first?.id) ??
    pool.find((t) => t.id !== first?.id);
  const paired = kind === "near" || kind === "apart";
  const max = first ? siteKeys(first.spec!).length : 1;

  const add = () => {
    if (!first || (paired && !other)) return;
    const next: Constraint = { kind, twin_id: first.id };
    if (kind === "reach_slots") next.count = Math.min(count, max);
    if (kind === "zone") next.side = side;
    if (paired) Object.assign(next, { other_id: other!.id, metres });
    onSave([...constraints, next]);
  };

  return (
    <details className={s.preferences} open={constraints.length > 0}>
      <summary>
        Preferences{constraints.length ? ` · ${constraints.length}` : ""}
      </summary>
      {constraints.length > 0 && (
        <ul className={s.preferenceList}>
          {constraints.map((c, i) => (
            <li key={i}>
              <span>{describe(c, name)}</span>
              <button
                aria-label={`Remove ${describe(c, name)}`}
                disabled={busy}
                onClick={() => onSave(constraints.filter((_, j) => j !== i))}
              >
                <X size={14} />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className={s.preferenceForm}>
        <select
          aria-label="Preference"
          value={kind}
          onChange={(e) => setKind(e.target.value as Kind)}
        >
          {KINDS.map((k) => (
            <option key={k.kind} value={k.kind}>
              {k.label}
            </option>
          ))}
        </select>
        <select
          aria-label="Instrument"
          value={first?.id ?? ""}
          onChange={(e) => setTwinId(e.target.value)}
        >
          {pool.map((t) => (
            <option key={t.id} value={t.id}>
              {t.spec!.name}
            </option>
          ))}
        </select>
        {kind === "reach_slots" && (
          <input
            type="number"
            aria-label="Slots to reach"
            min={1}
            max={max}
            value={Math.min(count, max)}
            onChange={(e) => setCount(Number(e.target.value))}
          />
        )}
        {kind === "zone" && (
          <select
            aria-label="Side of the bench"
            value={side}
            onChange={(e) => setSide(e.target.value as Side)}
          >
            {SIDES.map((v) => (
              <option key={v} value={v}>
                {v[0].toUpperCase() + v.slice(1)}
              </option>
            ))}
          </select>
        )}
        {paired && (
          <>
            <select
              aria-label="Second instrument"
              value={other?.id ?? ""}
              onChange={(e) => setOtherId(e.target.value)}
            >
              {pool
                .filter((t) => t.id !== first?.id)
                .map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.spec!.name}
                  </option>
                ))}
            </select>
            <label className={s.inlineCheck}>
              <input
                type="number"
                aria-label="Distance in metres"
                min={0.05}
                max={4}
                step={0.05}
                value={metres}
                onChange={(e) => setMetres(Number(e.target.value))}
              />
              m
            </label>
          </>
        )}
        <button
          className={studio.secondary}
          disabled={busy || !first || (paired && !other)}
          onClick={add}
        >
          <Plus size={14} /> Add
        </button>
      </div>
    </details>
  );
}
