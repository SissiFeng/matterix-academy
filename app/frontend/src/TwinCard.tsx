import { useEffect, useRef, useState } from "react";
import { Check, Download, Plus, Trash2, X } from "lucide-react";
import {
  layerLabels,
  layers,
  operationLabels,
  operations,
  vessels,
  type Layer,
  type LibraryMatch,
  type Twin,
  type TwinSpec,
} from "./instrumentTypes";
import s from "./InstrumentStudio.module.css";

const statusLabels: Record<Twin["status"], string> = {
  starting: "Submitting photo",
  generating: "Astra is building the twin",
  draft: "Review and confirm",
  ready: "Confirmed",
  failed: "Generation failed",
  submission_unknown: "Submission outcome unknown",
};

export type ResidualInput = {
  layer: Layer;
  step: number | null;
  predicted: string;
  observed: string;
  note: string;
};

function NumberField({
  label,
  value,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className={s.field}>
      {label}
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step ?? "any"}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </label>
  );
}

function ResidualForm({
  busy,
  onSubmit,
  onCancel,
}: {
  busy: boolean;
  onSubmit: (input: ResidualInput) => Promise<boolean>;
  onCancel: () => void;
}) {
  const [input, setInput] = useState<ResidualInput>({
    layer: "geometry",
    step: null,
    predicted: "",
    observed: "",
    note: "",
  });
  return (
    <form
      className={s.residualForm}
      onSubmit={async (e) => {
        e.preventDefault();
        if (await onSubmit(input)) onCancel();
      }}
    >
      <label className={s.field}>
        Which layer was wrong?
        <select
          value={input.layer}
          onChange={(e) =>
            setInput({ ...input, layer: e.target.value as Layer })
          }
        >
          {layers.map((layer) => (
            <option key={layer} value={layer}>
              {layerLabels[layer]}
            </option>
          ))}
        </select>
      </label>
      <label className={s.field}>
        Workflow step (optional)
        <input
          type="number"
          min={1}
          max={48}
          value={input.step ?? ""}
          onChange={(e) =>
            setInput({
              ...input,
              step: e.target.value ? Number(e.target.value) : null,
            })
          }
        />
      </label>
      <label className={s.field}>
        The twin predicted
        <input
          required
          maxLength={200}
          value={input.predicted}
          onChange={(e) => setInput({ ...input, predicted: e.target.value })}
        />
      </label>
      <label className={s.field}>
        The real instrument did
        <input
          required
          maxLength={200}
          value={input.observed}
          onChange={(e) => setInput({ ...input, observed: e.target.value })}
        />
      </label>
      <label className={s.field}>
        Note
        <input
          maxLength={400}
          value={input.note}
          onChange={(e) => setInput({ ...input, note: e.target.value })}
        />
      </label>
      <div className={s.actions}>
        <button className={s.primary} disabled={busy}>
          Record residual
        </button>
        <button type="button" className={s.secondary} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

export default function TwinCard({
  twin,
  busy,
  onConfirm,
  onRemove,
  onResidual,
  onDownload,
  onDirtyChange,
  onMatch,
}: {
  twin: Twin;
  busy: boolean;
  onConfirm: (spec: TwinSpec) => void;
  onRemove: () => void;
  onResidual: (input: ResidualInput) => Promise<boolean>;
  onDownload: () => void;
  onDirtyChange: (id: string, changed: boolean) => void;
  onMatch: (match: LibraryMatch) => void;
}) {
  const [draft, setDraft] = useState(twin.spec);
  const [reporting, setReporting] = useState(false);
  const baseline = useRef(JSON.stringify(twin.spec));
  const [conflict, setConflict] = useState(false);
  const serverSpec = JSON.stringify(twin.spec);
  useEffect(() => {
    if (serverSpec === baseline.current) return;
    if (
      JSON.stringify(draft) === baseline.current ||
      JSON.stringify(draft) === serverSpec
    ) {
      setDraft(twin.spec);
      baseline.current = serverSpec;
      setConflict(false);
    } else setConflict(true);
  }, [serverSpec, draft, twin.spec]);
  useEffect(() => {
    onDirtyChange(
      twin.id,
      JSON.stringify(draft) !== baseline.current || reporting,
    );
    return () => onDirtyChange(twin.id, false);
  }, [draft, reporting, twin.id, onDirtyChange]);
  const editable =
    !!draft && (twin.status === "draft" || twin.status === "ready");
  const changed = JSON.stringify(draft) !== JSON.stringify(twin.spec);
  const open = twin.residuals.filter((r) => r.resolved_in === null);
  // Detail grows only against an open residual; the server enforces the same rule.
  const mayGrow = (layer: Layer) =>
    !twin.confirmed || open.some((r) => r.layer === layer);
  const holds = draft?.operations.includes("load");
  const toggle = (op: (typeof operations)[number], on: boolean) => {
    if (!draft) return;
    const next = on
      ? operations.filter((o) => o === op || draft.operations.includes(o))
      : draft.operations.filter((o) => o !== op);
    const loads = next.includes("load");
    setDraft({
      ...draft,
      operations: next,
      consumables: draft.consumables.filter((c) => next.includes(c.used_by)),
      ...(op === "load" && {
        container: loads
          ? { vessel: "plate", max_volume_ul: 200 }
          : { vessel: "none", max_volume_ul: 0 },
        resource: { slots: loads ? 1 : 0 },
      }),
    });
  };
  return (
    <article className={s.card} data-status={twin.status} data-twin={twin.id}>
      {conflict && (
        <p role="alert">
          This instrument changed in another request. Your edits are preserved.{" "}
          <button
            onClick={() => {
              setDraft(twin.spec);
              baseline.current = serverSpec;
              setConflict(false);
            }}
          >
            Discard edits and reload instrument
          </button>
        </p>
      )}
      <header>
        <div>
          <strong>{twin.spec?.name ?? "New instrument"}</strong>
          <small>
            {twin.source === "astra_image"
              ? "From photo · GPT-6 Astra"
              : twin.source === "simready_asset"
                ? `SimReady asset · ${twin.asset?.provider ?? "unknown"}`
                : twin.source === "chemlab_asset"
                  ? "ChemLab reference · CC-BY-NC-4.0"
                  : "Academy USD template"}
            {twin.confirmed && ` · revision ${twin.revision}`}
          </small>
        </div>
        <span className={s.badge}>{statusLabels[twin.status]}</span>
      </header>
      {twin.message && <p className={s.message}>{twin.message}</p>}
      {!twin.confirmed && !!twin.matches?.length && (
        <section className={s.matches} aria-label="Library matches">
          <strong>
            {twin.identification?.model
              ? `Astra read ${[twin.identification.maker, twin.identification.model].filter(Boolean).join(" ")}`
              : "Astra found similar library instruments"}
          </strong>
          {twin.identification && (
            <small>
              {twin.identification.confidence} confidence
              {twin.identification.evidence &&
                ` · ${twin.identification.evidence}`}
            </small>
          )}
          <ul>
            {twin.matches.map((m) => {
              const using =
                twin.source === `${m.collection}_asset` &&
                twin.asset?.id === m.id;
              return (
                <li key={`${m.collection}:${m.id}`}>
                  <span>
                    <strong>{m.name}</strong>
                    <small>
                      {m.size_m.map((v) => v.toFixed(2)).join(" × ")} m ·{" "}
                      {m.label}
                    </small>
                    <span className={s.matchTags}>
                      {m.verified && <em>Label confirmed</em>}
                      {m.suggested_by === "label_text" && (
                        <em>Found from label text</em>
                      )}
                      <em data-collection={m.collection}>
                        {m.collection === "chemlab"
                          ? "ChemLab · NC"
                          : "SimReady"}
                      </em>
                    </span>
                  </span>
                  <button
                    className={using ? s.ghost : s.secondary}
                    disabled={busy || using}
                    aria-label={`Use ${m.name} footprint`}
                    onClick={() => onMatch(m)}
                  >
                    {using ? "In use" : "Use footprint"}
                  </button>
                </li>
              );
            })}
          </ul>
          <small>
            A match replaces the photo sketch with the catalogued footprint and
            its teaching defaults. Check it is your instrument before
            confirming.
          </small>
        </section>
      )}
      {twin.asset && (
        <p className={s.muted}>
          Footprint from{" "}
          <a href={twin.asset.url} target="_blank" rel="noreferrer">
            {twin.asset.attribution}
          </a>
        </p>
      )}
      {editable && draft && (
        <>
          <label className={s.field}>
            Instrument name
            <input
              value={draft.name}
              maxLength={80}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            />
          </label>
          <fieldset className={s.ops}>
            <legend>State · what can it do?</legend>
            {operations.map((op) => (
              <label key={op}>
                <input
                  type="checkbox"
                  checked={draft.operations.includes(op)}
                  onChange={(e) => toggle(op, e.target.checked)}
                />
                {operationLabels[op]}
              </label>
            ))}
          </fieldset>
          {holds && (
            <fieldset className={s.layer}>
              <legend>Container · volume · resources</legend>
              <label className={s.field}>
                Vessel
                <select
                  value={draft.container.vessel}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      container: {
                        ...draft.container,
                        vessel: e.target
                          .value as TwinSpec["container"]["vessel"],
                      },
                    })
                  }
                >
                  {vessels
                    .filter((v) => v !== "none")
                    .map((v) => (
                      <option key={v}>{v}</option>
                    ))}
                </select>
              </label>
              <NumberField
                label="Max volume (µL)"
                value={draft.container.max_volume_ul}
                min={1}
                max={1_000_000}
                onChange={(max_volume_ul) =>
                  setDraft({
                    ...draft,
                    container: { ...draft.container, max_volume_ul },
                  })
                }
              />
              <NumberField
                label="Slots"
                value={draft.resource.slots}
                min={1}
                max={96}
                step={1}
                onChange={(slots) =>
                  setDraft({ ...draft, resource: { slots } })
                }
              />
            </fieldset>
          )}
          <fieldset className={s.layer}>
            <legend>Constraints</legend>
            {draft.operations.includes("heat") && (
              <>
                <NumberField
                  label="Min °C"
                  value={draft.limits.min_temp_c}
                  min={4}
                  max={120}
                  onChange={(min_temp_c) =>
                    setDraft({
                      ...draft,
                      limits: { ...draft.limits, min_temp_c },
                    })
                  }
                />
                <NumberField
                  label="Max °C"
                  value={draft.limits.max_temp_c}
                  min={4}
                  max={120}
                  onChange={(max_temp_c) =>
                    setDraft({
                      ...draft,
                      limits: { ...draft.limits, max_temp_c },
                    })
                  }
                />
              </>
            )}
            <NumberField
              label="Longest mix/wait (s)"
              value={draft.limits.max_duration_s}
              min={1}
              max={1000}
              onChange={(max_duration_s) =>
                setDraft({
                  ...draft,
                  limits: { ...draft.limits, max_duration_s },
                })
              }
            />
          </fieldset>
          <fieldset className={s.layer}>
            <legend>Consumables</legend>
            {draft.consumables.length === 0 && (
              <small className={s.hint}>None modelled.</small>
            )}
            {draft.consumables.map((item, i) => {
              const set = (patch: Partial<typeof item>) =>
                setDraft({
                  ...draft,
                  consumables: draft.consumables.map((c, j) =>
                    j === i ? { ...c, ...patch } : c,
                  ),
                });
              return (
                <div key={i} className={s.consumable}>
                  <input
                    aria-label="Consumable name"
                    value={item.name}
                    maxLength={40}
                    onChange={(e) => set({ name: e.target.value })}
                  />
                  <select
                    aria-label={`${item.name} used by`}
                    value={item.used_by}
                    onChange={(e) =>
                      set({ used_by: e.target.value as typeof item.used_by })
                    }
                  >
                    {draft.operations.map((op) => (
                      <option key={op} value={op}>
                        {operationLabels[op]}
                      </option>
                    ))}
                  </select>
                  <input
                    type="number"
                    aria-label={`${item.name} per use`}
                    min={1}
                    max={100}
                    value={item.per_use}
                    onChange={(e) => set({ per_use: Number(e.target.value) })}
                  />
                  <input
                    type="number"
                    aria-label={`${item.name} stock`}
                    min={0}
                    max={10000}
                    value={item.stock}
                    onChange={(e) => set({ stock: Number(e.target.value) })}
                  />
                  <button
                    className={s.ghost}
                    aria-label={`Remove ${item.name}`}
                    onClick={() =>
                      setDraft({
                        ...draft,
                        consumables: draft.consumables.filter(
                          (_, j) => j !== i,
                        ),
                      })
                    }
                  >
                    <X size={14} />
                  </button>
                </div>
              );
            })}
            {draft.consumables.length < 4 && (
              <button
                className={s.secondary}
                disabled={!mayGrow("consumable")}
                title={
                  mayGrow("consumable")
                    ? undefined
                    : "Record a consumable residual first"
                }
                onClick={() =>
                  setDraft({
                    ...draft,
                    consumables: [
                      ...draft.consumables,
                      {
                        name: `Consumable ${draft.consumables.length + 1}`,
                        used_by: draft.operations[0],
                        per_use: 1,
                        stock: 10,
                      },
                    ],
                  })
                }
              >
                <Plus size={14} /> Add consumable
              </button>
            )}
          </fieldset>
          <p className={s.assumptions}>
            <b>Assumptions</b> {draft.assumptions}
          </p>
        </>
      )}
      {twin.confirmed && (
        <section className={s.residuals} aria-label="Failure residuals">
          <div className={s.layerChips}>
            {layers.map((layer) => {
              const count = open.filter((r) => r.layer === layer).length;
              return (
                <span key={layer} data-open={count > 0 || undefined}>
                  {layerLabels[layer]}
                  {count > 0 && ` · ${count}`}
                </span>
              );
            })}
          </div>
          {twin.residuals.map((r) => (
            <div
              key={r.id}
              className={s.residual}
              data-resolved={r.resolved_in !== null || undefined}
            >
              <strong>
                {layerLabels[r.layer]}
                {r.step && ` · step ${r.step}`}
              </strong>
              <span>
                Predicted {r.predicted}; observed {r.observed}.
              </span>
              {r.note && <small>{r.note}</small>}
              <small>
                {r.resolved_in
                  ? `Addressed in revision ${r.resolved_in}`
                  : `Open against revision ${r.revision}`}
              </small>
            </div>
          ))}
          {reporting ? (
            <ResidualForm
              busy={busy}
              onSubmit={onResidual}
              onCancel={() => setReporting(false)}
            />
          ) : (
            <button className={s.secondary} onClick={() => setReporting(true)}>
              Record a failure residual
            </button>
          )}
        </section>
      )}
      <footer>
        {editable && draft && (!twin.confirmed || changed) && (
          <button
            className={s.primary}
            disabled={
              busy || conflict || !draft.name.trim() || !draft.operations.length
            }
            onClick={() => onConfirm({ ...draft, name: draft.name.trim() })}
          >
            <Check size={15} />{" "}
            {twin.confirmed ? "Save revision" : "Confirm twin"}
          </button>
        )}
        {twin.confirmed && (
          <button className={s.secondary} onClick={onDownload}>
            <Download size={15} /> USD
          </button>
        )}
        <button
          className={s.ghost}
          disabled={busy}
          onClick={onRemove}
          aria-label={`Remove ${twin.spec?.name ?? "instrument"}`}
        >
          <Trash2 size={15} />
        </button>
      </footer>
    </article>
  );
}
