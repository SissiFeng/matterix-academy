import { useRef, useState } from "react";
import { ArrowRight, FileUp, Search, Sparkles } from "lucide-react";
import {
  DEFAULT_SAMPLE,
  operationLabels,
  siteKeys,
  type Brief,
  type BriefRole,
  type BriefStep,
  type InstrumentCatalog,
  type Twin,
} from "./instrumentTypes";
import studio from "./InstrumentStudio.module.css";
import s from "./BriefPanel.module.css";

const EXAMPLE =
  "Load 150 µL of sample on a plate in the heater, heat it to 37 °C for a while, then move the plate to the reader and read it.";

/** A twin can play a role when it supports every operation and the vessel. */
export function fits(role: BriefRole, twin: Twin) {
  const spec = twin.spec;
  return (
    !!spec &&
    role.operations.every((op) => spec.operations.includes(op)) &&
    (role.vessel === "none" || spec.container.vessel === role.vessel) &&
    siteKeys(spec).length >= (role.reach_slots ?? 0)
  );
}

/** Why the drafted steps cannot become the workflow yet, or null when they can. */
export function applyBlocker(brief: Brief | null, twins: Twin[]) {
  const draft = brief?.draft;
  if (!draft) return "Draft a workflow from a description first.";
  const used = new Set(
    draft.steps.flatMap((step) =>
      [step.role, step.source_role, step.target_role].filter(Boolean),
    ),
  );
  const roles = draft.roles.filter((r) => used.has(r.key));
  const missing = roles.filter((r) => !brief.bindings[r.key]);
  if (missing.length)
    return `Choose an instrument for ${missing.map((r) => r.name).join(", ")}.`;
  const unconfirmed = roles.filter(
    (r) => !twins.find((t) => t.id === brief.bindings[r.key])?.confirmed,
  );
  if (unconfirmed.length)
    return `Confirm the instrument for ${unconfirmed.map((r) => r.name).join(", ")}.`;
  return null;
}

function stepText(step: BriefStep, roles: Map<string, BriefRole>) {
  const role = roles.get(step.role)?.name ?? step.role;
  const sample =
    step.sample && step.sample !== DEFAULT_SAMPLE ? ` · ${step.sample}` : "";
  if (step.operation === "transfer")
    return `${role} · ${roles.get(step.source_role)?.name} → ${roles.get(step.target_role)?.name}${sample}`;
  const unit =
    step.operation === "load"
      ? ` ${step.value} µL`
      : step.operation === "heat"
        ? ` ${step.value} °C`
        : step.operation === "mix" || step.operation === "wait"
          ? ` ${step.value} s`
          : "";
  return `${role} · ${operationLabels[step.operation]}${unit}${sample}`;
}

export default function BriefPanel({
  catalog,
  busy,
  onDescribe,
  onImport,
  onSchema,
  onNext,
}: {
  catalog: InstrumentCatalog;
  busy: boolean;
  onDescribe: (text: string) => void;
  /** A workflow file from another tool, in the draft schema. */
  onImport: (name: string, draft: unknown) => void;
  onSchema: () => void;
  onNext: () => void;
}) {
  const brief = catalog.brief;
  // Servers from before Nova drafting report only Astra.
  const drafts = catalog.brief_available ?? catalog.astra_available;
  const model = catalog.brief_model ?? "GPT-6 Astra";
  const [text, setText] = useState(
    brief?.source === "import" ? "" : (brief?.text ?? ""),
  );
  const [fileError, setFileError] = useState("");
  const file = useRef<HTMLInputElement>(null);
  const drafting =
    brief?.status === "generating" || brief?.status === "starting";
  const roles = new Map(brief?.draft?.roles.map((r) => [r.key, r]) ?? []);
  const name = (id?: string) =>
    catalog.twins.find((t) => t.id === id)?.spec?.name;

  return (
    <>
      <h2>Describe the workflow</h2>
      <label className={s.describe}>
        <span className={s.srOnly}>Workflow description</span>
        <textarea
          rows={5}
          maxLength={2000}
          value={text}
          placeholder={EXAMPLE}
          onChange={(e) => setText(e.target.value)}
        />
      </label>
      <div className={studio.actions}>
        <button
          className={studio.primary}
          disabled={busy || drafting || !drafts || text.trim().length < 10}
          onClick={() => onDescribe(text.trim())}
        >
          <Sparkles size={15} />{" "}
          {drafting
            ? "Drafting…"
            : brief?.draft
              ? "Redraft"
              : "Draft roles and steps"}
        </button>
        <button
          className={studio.secondary}
          disabled={busy || drafting}
          onClick={() => file.current?.click()}
        >
          <FileUp size={14} /> Import file
        </button>
        <input
          ref={file}
          type="file"
          accept="application/json,.json"
          className={s.srOnly}
          aria-label="Workflow file"
          onChange={async (e) => {
            const chosen = e.target.files?.[0];
            e.target.value = "";
            if (!chosen) return;
            setFileError("");
            try {
              const parsed = JSON.parse(await chosen.text());
              onImport(
                chosen.name.replace(/\.json$/i, "").slice(0, 120) ||
                  "Imported workflow",
                parsed.draft ?? parsed,
              );
            } catch {
              setFileError(`${chosen.name} is not a JSON workflow file.`);
            }
          }}
        />
        <button className={studio.secondary} onClick={onNext}>
          {brief?.draft ? "Choose instruments" : "Skip to instruments"}{" "}
          <ArrowRight size={14} />
        </button>
      </div>
      {fileError && (
        <p className={s.problem} role="status">
          {fileError}
        </p>
      )}
      {brief?.source === "import" && brief.draft && (
        <p className={studio.muted}>From {brief.text}</p>
      )}
      {!drafts && (
        <p className={studio.muted}>
          Drafting needs a language model, which is not configured here. Add
          instruments and build the steps by hand.
        </p>
      )}
      {brief &&
        (brief.status === "failed" ||
          brief.status === "submission_unknown") && (
          <p className={s.problem} role="status">
            {brief.message}
          </p>
        )}

      {brief?.draft && (
        <div className={s.draft} aria-live="polite">
          <section aria-label="Instrument roles">
            <h3>Instruments it needs</h3>
            <ul className={s.roles}>
              {brief.draft.roles.map((role) => (
                <li key={role.key}>
                  <strong>{role.name}</strong>
                  <small>
                    {role.operations
                      .map((op) => operationLabels[op])
                      .join(" · ")}
                    {role.vessel !== "none" && ` · ${role.vessel}`}
                    {!!role.reach_slots &&
                      ` · arm reaches ${role.reach_slots} slots`}
                  </small>
                  <span
                    className={brief.bindings[role.key] ? s.bound : s.unbound}
                  >
                    {name(brief.bindings[role.key]) ?? "Not chosen"}
                  </span>
                </li>
              ))}
            </ul>
          </section>
          <section aria-label="Drafted steps">
            <h3>Steps</h3>
            <ol className={s.draftSteps}>
              {brief.draft.steps.map((step, i) => (
                <li key={i}>{stepText(step, roles)}</li>
              ))}
            </ol>
          </section>
          {!!brief.draft.preferences?.length && (
            <section aria-label="Layout preferences">
              <h3>Layout</h3>
              <ul className={s.draftSteps}>
                {brief.draft.preferences.map((p, i) => (
                  <li key={i}>
                    {roles.get(p.role)?.name}
                    {p.kind === "zone"
                      ? ` on the ${p.side}`
                      : ` ${p.kind === "near" ? "within" : "at least"} ${p.metres} m ${p.kind === "near" ? "of" : "from"} ${roles.get(p.other_role)?.name}`}
                  </li>
                ))}
              </ul>
            </section>
          )}
          {brief.draft.assumptions.length > 0 && (
            <details className={s.details}>
              <summary>Assumptions</summary>
              <ul>
                {brief.draft.assumptions.map((a, i) => (
                  <li key={i}>{a}</li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
      <details className={s.details}>
        <summary>How drafting works</summary>
        <p>
          {model} on Amazon Bedrock reads the description and drafts instrument
          roles and steps against the same bounded operations as the step
          editor. It never picks a model: you choose each instrument, then the
          drafted steps become your workflow and its slot and layout wishes
          become layout preferences.
        </p>
        <p>
          A workflow exported from an orchestrator can be imported instead when
          it follows the{" "}
          <button className={s.link} onClick={onSchema}>
            draft schema
          </button>
          : roles, steps on named samples, slots to reach and layout
          preferences.
        </p>
      </details>
    </>
  );
}

export function RoleBindings({
  brief,
  twins,
  busy,
  finding,
  onBind,
  onFind,
}: {
  brief: Brief;
  twins: Twin[];
  busy: boolean;
  finding: string | null;
  onBind: (role: string, twinId: string | null) => void;
  onFind: (role: BriefRole) => void;
}) {
  return (
    <section className={s.bindings} aria-label="Instruments for your workflow">
      <h2>Instruments for your workflow</h2>
      <ul>
        {brief.draft!.roles.map((role) => {
          const bound = brief.bindings[role.key] ?? "";
          const options = twins.filter((t) => t.id === bound || fits(role, t));
          return (
            <li
              key={role.key}
              className={finding === role.key ? s.finding : ""}
            >
              <span>
                <strong>{role.name}</strong>
                <small>
                  {role.operations.map((op) => operationLabels[op]).join(" · ")}
                  {role.vessel !== "none" && ` · ${role.vessel}`}
                  {!!role.reach_slots && ` · ${role.reach_slots}+ slots`}
                </small>
              </span>
              <select
                aria-label={`${role.name} instrument`}
                value={bound}
                disabled={busy}
                onChange={(e) => onBind(role.key, e.target.value || null)}
              >
                <option value="">
                  {options.length ? "Not chosen" : "None added yet"}
                </option>
                {options.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.spec!.name}
                    {t.confirmed ? "" : " (unconfirmed)"}
                  </option>
                ))}
              </select>
              <button
                className={studio.secondary}
                aria-pressed={finding === role.key}
                onClick={() => onFind(role)}
              >
                <Search size={14} /> Find
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
