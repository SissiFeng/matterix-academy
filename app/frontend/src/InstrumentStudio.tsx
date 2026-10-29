import {
  Suspense,
  lazy,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  ArrowDown,
  ArrowUp,
  Camera,
  Download,
  Play,
  Plug,
  Plus,
  Trash2,
} from "lucide-react";
import { api, ApiError, json } from "./api";
import {
  operationLabels,
  type ConnectorPackage,
  type InstrumentCatalog,
  type Operation,
  type Step,
  type Twin,
} from "./instrumentTypes";
import s from "./InstrumentStudio.module.css";
import TwinCard from "./TwinCard";

const TwinScene = lazy(() => import("./TwinScene"));
type Tab = "instruments" | "workflow" | "connectors";
const tabs: { id: Tab; label: string }[] = [
  { id: "instruments", label: "1 · Instruments" },
  { id: "workflow", label: "2 · Workflow" },
  { id: "connectors", label: "3 · Connectors" },
];
const templateLabels: Record<string, string> = {
  "liquid-handler": "Liquid handler",
  heater: "Heating station",
  reader: "Plate reader",
  "transfer-arm": "Transfer robot",
};
const units: Partial<Record<Operation, [string, string]>> = {
  load: ["volume", "µL"],
  heat: ["temperature", "°C"],
  mix: ["duration", "s"],
  wait: ["duration", "s"],
};

/** Downscale to ≤1024 px JPEG so uploads stay well below the 1 MB limit. */
async function encodePhoto(file: File) {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, 1024 / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext("2d")!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  const blob = await new Promise<Blob>((resolve, reject) =>
    canvas.toBlob(
      (b) => (b ? resolve(b) : reject(new Error("Could not read this photo."))),
      "image/jpeg",
      0.85,
    ),
  );
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000)
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

function save(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
  const link = Object.assign(document.createElement("a"), {
    href: url,
    download: name,
  });
  link.click();
  URL.revokeObjectURL(url);
}

export default function InstrumentStudio() {
  const [catalog, setCatalog] = useState<InstrumentCatalog | null>(null);
  const [tab, setTab] = useState<Tab>("instruments");
  const [steps, setSteps] = useState<Step[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [frame, setFrame] = useState(-1);
  const [connector, setConnector] = useState<ConnectorPackage | null>(null);
  const version = useRef(0);
  const dirty = useRef(false);

  const accept = useCallback((next: InstrumentCatalog) => {
    version.current = next.version;
    setCatalog(next);
    if (!dirty.current) setSteps(next.steps);
  }, []);
  const load = useCallback(
    async () => accept(await api<InstrumentCatalog>("/twins")),
    [accept],
  );
  useEffect(() => {
    load().catch((e) => setError((e as Error).message));
  }, [load]);

  const mutate = async (path: string, body: object, method = "POST") => {
    setBusy(true);
    setError("");
    try {
      accept(
        await api<InstrumentCatalog>(
          path,
          json({ expected_version: version.current, ...body }, method),
        ),
      );
      return true;
    } catch (e) {
      setError((e as Error).message);
      if (e instanceof ApiError && e.status === 409)
        await load().catch(() => undefined);
      return false;
    } finally {
      setBusy(false);
    }
  };

  const generating = catalog?.twins.find((t) => t.status === "generating");
  useEffect(() => {
    if (!generating) return;
    const timer = window.setInterval(async () => {
      try {
        accept(
          await api<InstrumentCatalog>(
            `/twins/${generating.id}/poll`,
            json({ expected_version: version.current }),
          ),
        );
      } catch (e) {
        if (e instanceof ApiError && e.status === 409)
          load().catch(() => undefined);
        else setError((e as Error).message);
      }
    }, 3000);
    return () => window.clearInterval(timer);
  }, [generating?.id, accept, load]);

  const run = catalog?.runs[0];
  useEffect(() => {
    if (!run) return;
    setFrame(0);
    const timer = window.setInterval(
      () =>
        setFrame((f) =>
          f + 1 >= run.trace.length ? (window.clearInterval(timer), f) : f + 1,
        ),
      900,
    );
    return () => window.clearInterval(timer);
  }, [run?.id]);

  if (!catalog)
    return (
      <section className={s.page} aria-label="Bring your own instrument">
        {error ? (
          <div className={s.alert}>{error}</div>
        ) : (
          <p className={s.muted}>Loading your instruments…</p>
        )}
      </section>
    );

  const confirmed = catalog.twins.filter((t) => t.confirmed);
  const stations = confirmed.filter((t) => t.spec!.operations.includes("load"));
  const name = (id: string | null) =>
    catalog.twins.find((t) => t.id === id)?.spec?.name ?? "—";
  const editSteps = (next: Step[]) => {
    dirty.current = true;
    setSteps(next);
  };
  const stepFor = (device: Twin, operation?: Operation): Step => {
    const op = operation ?? device.spec!.operations[0];
    return {
      device_id: device.id,
      operation: op,
      source_id: op === "transfer" ? (stations[0]?.id ?? null) : null,
      target_id: op === "transfer" ? (stations[1]?.id ?? null) : null,
      value:
        op === "heat"
          ? 37
          : op === "load"
            ? 100
            : op === "mix" || op === "wait"
              ? 10
              : 1,
    };
  };
  const trace =
    run && frame >= 0 ? run.trace[Math.min(frame, run.trace.length - 1)] : null;

  return (
    <section className={s.page} aria-labelledby="byo-instrument">
      <div className={s.heading}>
        <div>
          <span className={s.eyebrow}>BRING YOUR OWN INSTRUMENT</span>
          <h2 id="byo-instrument">
            Photograph an instrument. Run it as a twin.
          </h2>
          <p>
            Upload a photo and GPT-6 Astra on Amazon Bedrock sketches a simple
            3D twin, or start from an Academy USD template. Confirm the
            instruments you will use, design a workflow across them, then run it
            through mock SiLA 2 connectors.
          </p>
        </div>
      </div>
      <p className={s.notice}>
        Teaching twins are minimum sufficient models: volume, slots, coarse
        geometry, vessel, consumables, state and limits. Runs are synthetic and
        are not Isaac/GPU, physical robot or chemical validation.
      </p>
      {error && (
        <div className={s.alert} role="alert">
          {error}
          <button onClick={() => setError("")}>Dismiss</button>
        </div>
      )}
      <div className={s.tabs} role="tablist">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            className={tab === t.id ? s.activeTab : ""}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className={s.workspace}>
        <section className={s.viewport} aria-label="Workcell preview">
          <div className={s.viewportBar}>
            <span>
              {trace
                ? `Step ${trace.step} · ${operationLabels[trace.operation]} · ${name(trace.device_id)}`
                : `${catalog.twins.length} instrument${catalog.twins.length === 1 ? "" : "s"} · drag to orbit`}
            </span>
            <span>SYNTHETIC TWIN</span>
          </div>
          <Suspense fallback={<div className={s.scene} />}>
            <TwinScene
              twins={tab === "instruments" ? catalog.twins : confirmed}
              active={tab === "workflow" ? trace?.device_id : null}
              sample={tab === "workflow" ? trace?.location : null}
            />
          </Suspense>
          {tab === "workflow" && trace && (
            <dl className={s.state}>
              <div>
                <dt>Sample at</dt>
                <dd>{name(trace.location)}</dd>
              </div>
              <div>
                <dt>Volume</dt>
                <dd>
                  {trace.volume_ul} µL · {trace.vessel}
                </dd>
              </div>
              <div>
                <dt>Temperature</dt>
                <dd>{trace.temperature_c} °C</dd>
              </div>
              <div>
                <dt>Mixed</dt>
                <dd>{trace.mixed ? "Yes" : "No"}</dd>
              </div>
              <div>
                <dt>Elapsed</dt>
                <dd>{trace.elapsed_s} s</dd>
              </div>
              {Object.entries(trace.consumables).flatMap(([id, items]) =>
                Object.entries(items).map(([item, left]) => (
                  <div key={id + item}>
                    <dt>{item} left</dt>
                    <dd>{left}</dd>
                  </div>
                )),
              )}
            </dl>
          )}
        </section>

        <aside className={s.panel}>
          {tab === "instruments" && (
            <>
              <h2>Add an instrument</h2>
              <label
                className={`${s.upload} ${!catalog.astra_available ? s.disabled : ""}`}
              >
                <Camera size={18} />
                <span>
                  <strong>Upload a photo</strong>
                  <small>
                    {catalog.astra_available
                      ? "PNG, JPEG or WebP · GPT-6 Astra builds a draft twin"
                      : "Astra is not configured on this server. Use a template."}
                  </small>
                </span>
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  disabled={busy || !catalog.astra_available}
                  onChange={async (e) => {
                    const file = e.target.files?.[0];
                    e.target.value = "";
                    if (!file) return;
                    try {
                      await mutate("/twins", {
                        id: crypto.randomUUID(),
                        image: await encodePhoto(file),
                        mime: "image/jpeg",
                      });
                    } catch (err) {
                      setError((err as Error).message);
                    }
                  }}
                />
              </label>
              <div className={s.templates}>
                {Object.keys(catalog.templates).map((id) => (
                  <button
                    key={id}
                    className={s.secondary}
                    disabled={busy}
                    onClick={() =>
                      mutate("/twins", {
                        id: crypto.randomUUID(),
                        template_id: id,
                      })
                    }
                  >
                    <Plus size={14} /> {templateLabels[id] ?? id}
                  </button>
                ))}
              </div>
              {catalog.twins.length === 0 && (
                <p className={s.muted}>
                  No instruments yet. Add a photo or a template to start your
                  workcell.
                </p>
              )}
              {catalog.twins.map((twin) => (
                <TwinCard
                  key={twin.id}
                  twin={twin}
                  busy={busy}
                  onConfirm={(spec) =>
                    mutate(`/twins/${twin.id}/confirm`, { spec }, "PUT")
                  }
                  onRemove={() => mutate(`/twins/${twin.id}`, {}, "DELETE")}
                  onResidual={(input) =>
                    mutate(`/twins/${twin.id}/residuals`, input)
                  }
                  onDownload={async () => {
                    try {
                      const response = await fetch(
                        `/api/twins/${twin.id}/usd`,
                        { credentials: "same-origin" },
                      );
                      if (!response.ok)
                        throw new Error("Could not download the USD file.");
                      save(`${twin.spec!.name}.usda`, await response.text());
                    } catch (e) {
                      setError((e as Error).message);
                    }
                  }}
                />
              ))}
            </>
          )}

          {tab === "workflow" && (
            <>
              <h2>Design the workflow</h2>
              {confirmed.length === 0 ? (
                <p className={s.muted}>
                  Confirm at least one instrument first.
                </p>
              ) : (
                <>
                  <p className={s.muted}>
                    One sample moves through your instruments. Load it once,
                    transfer it between stations, and act on it where it is.
                  </p>
                  <ol className={s.steps}>
                    {steps.map((step, i) => {
                      const device = confirmed.find(
                        (t) => t.id === step.device_id,
                      );
                      const replace = (next: Step) =>
                        editSteps(steps.map((x, j) => (j === i ? next : x)));
                      return (
                        <li
                          key={i}
                          className={
                            trace && run?.trace[frame]?.step === i + 1
                              ? s.currentStep
                              : ""
                          }
                        >
                          <span className={s.stepIndex}>{i + 1}</span>
                          <div className={s.stepFields}>
                            <select
                              aria-label={`Step ${i + 1} instrument`}
                              value={step.device_id}
                              onChange={(e) =>
                                replace(
                                  stepFor(
                                    confirmed.find(
                                      (t) => t.id === e.target.value,
                                    )!,
                                  ),
                                )
                              }
                            >
                              {confirmed.map((t) => (
                                <option key={t.id} value={t.id}>
                                  {t.spec!.name}
                                </option>
                              ))}
                            </select>
                            <select
                              aria-label={`Step ${i + 1} operation`}
                              value={step.operation}
                              onChange={(e) =>
                                replace(
                                  stepFor(device!, e.target.value as Operation),
                                )
                              }
                            >
                              {device?.spec!.operations.map((op) => (
                                <option key={op} value={op}>
                                  {operationLabels[op]}
                                </option>
                              ))}
                            </select>
                            {step.operation === "transfer" &&
                              (["source_id", "target_id"] as const).map(
                                (field) => (
                                  <select
                                    key={field}
                                    aria-label={`Step ${i + 1} ${field === "source_id" ? "from" : "to"}`}
                                    value={step[field] ?? ""}
                                    onChange={(e) =>
                                      replace({
                                        ...step,
                                        [field]: e.target.value,
                                      })
                                    }
                                  >
                                    <option value="" disabled>
                                      {field === "source_id" ? "From…" : "To…"}
                                    </option>
                                    {stations.map((t) => (
                                      <option key={t.id} value={t.id}>
                                        {field === "source_id"
                                          ? "From "
                                          : "To "}
                                        {t.spec!.name}
                                      </option>
                                    ))}
                                  </select>
                                ),
                              )}
                            {step.operation in units && (
                              <label className={s.inline}>
                                <input
                                  type="number"
                                  aria-label={`Step ${i + 1} ${units[step.operation]![0]}`}
                                  value={step.value}
                                  min={step.operation === "heat" ? 4 : 0.001}
                                  max={
                                    step.operation === "heat"
                                      ? 120
                                      : step.operation === "load"
                                        ? 1_000_000
                                        : 1000
                                  }
                                  onChange={(e) =>
                                    replace({
                                      ...step,
                                      value: Number(e.target.value),
                                    })
                                  }
                                />
                                {units[step.operation]![1]}
                              </label>
                            )}
                          </div>
                          <div className={s.stepTools}>
                            <button
                              aria-label="Move up"
                              disabled={i === 0}
                              onClick={() =>
                                editSteps(
                                  steps.map((x, j) =>
                                    j === i - 1
                                      ? steps[i]
                                      : j === i
                                        ? steps[i - 1]
                                        : x,
                                  ),
                                )
                              }
                            >
                              <ArrowUp size={14} />
                            </button>
                            <button
                              aria-label="Move down"
                              disabled={i === steps.length - 1}
                              onClick={() =>
                                editSteps(
                                  steps.map((x, j) =>
                                    j === i + 1
                                      ? steps[i]
                                      : j === i
                                        ? steps[i + 1]
                                        : x,
                                  ),
                                )
                              }
                            >
                              <ArrowDown size={14} />
                            </button>
                            <button
                              aria-label={`Remove step ${i + 1}`}
                              onClick={() =>
                                editSteps(steps.filter((_, j) => j !== i))
                              }
                            >
                              <Trash2 size={14} />
                            </button>
                          </div>
                        </li>
                      );
                    })}
                  </ol>
                  <button
                    className={s.secondary}
                    disabled={steps.length >= 48}
                    onClick={() => editSteps([...steps, stepFor(confirmed[0])])}
                  >
                    <Plus size={14} /> Add step
                  </button>
                  <div className={s.actions}>
                    <button
                      className={s.secondary}
                      disabled={busy || !dirty.current}
                      onClick={async () => {
                        dirty.current = false;
                        if (
                          !(await mutate("/twins/workflow", { steps }, "PUT"))
                        )
                          dirty.current = true;
                      }}
                    >
                      Save workflow
                    </button>
                    <button
                      className={s.primary}
                      disabled={busy || dirty.current || !catalog.steps.length}
                      onClick={() => mutate("/twins/workflow/run", {})}
                    >
                      <Play size={15} /> Run on mock connectors
                    </button>
                  </div>
                  {run && (
                    <div className={s.result}>
                      <strong>
                        Last run ·{" "}
                        {new Date(run.created_at).toLocaleTimeString()}
                      </strong>
                      <ol>
                        {run.trace.map((t) => (
                          <li
                            key={t.step}
                            className={t.step - 1 <= frame ? "" : s.pending}
                          >
                            {t.step}. {name(t.device_id)} ·{" "}
                            {operationLabels[t.operation]}
                            {t.measurement &&
                              ` → ${t.measurement.volume_ul} µL, ${t.measurement.temperature_c} °C, ${t.measurement.mixed ? "mixed" : "not mixed"}`}
                          </li>
                        ))}
                      </ol>
                      <small>
                        Synthetic · mock SiLA 2 connectors · teaching state only
                      </small>
                    </div>
                  )}
                </>
              )}
            </>
          )}

          {tab === "connectors" && (
            <>
              <h2>Connect each instrument</h2>
              {confirmed.length === 0 && (
                <p className={s.muted}>
                  Confirm an instrument to generate its connector.
                </p>
              )}
              {confirmed.map((twin) => (
                <article key={twin.id} className={s.card}>
                  <header>
                    <div>
                      <strong>{twin.spec!.name}</strong>
                      <small>
                        {twin
                          .spec!.operations.map((o) => operationLabels[o])
                          .join(" · ")}
                      </small>
                    </div>
                  </header>
                  <div
                    className={s.modes}
                    role="radiogroup"
                    aria-label={`${twin.spec!.name} connector`}
                  >
                    <label className={s.mode}>
                      <input
                        type="radio"
                        checked={twin.mode === "mock"}
                        readOnly
                      />
                      <span>
                        <strong>Mock SiLA 2</strong>
                        <small>Active · runs workflows synthetically</small>
                      </span>
                    </label>
                    <label
                      className={`${s.mode} ${s.disabled}`}
                      title={catalog.real_reason}
                    >
                      <input
                        type="radio"
                        checked={twin.mode === "real"}
                        disabled={!catalog.real_available || busy}
                        onChange={() =>
                          mutate(
                            `/twins/${twin.id}/connector`,
                            { mode: "real" },
                            "PUT",
                          )
                        }
                      />
                      <span>
                        <strong>Real device</strong>
                        <small>Locked until a connector is qualified</small>
                      </span>
                    </label>
                  </div>
                  <footer>
                    <button
                      className={s.secondary}
                      onClick={async () => {
                        try {
                          setConnector(
                            await api<ConnectorPackage>(
                              `/twins/${twin.id}/sila`,
                            ),
                          );
                        } catch (e) {
                          setError((e as Error).message);
                        }
                      }}
                    >
                      <Plug size={15} /> View mock connector
                    </button>
                  </footer>
                </article>
              ))}
              {confirmed.length > 0 && (
                <p className={s.notice}>{catalog.real_reason}</p>
              )}
              {connector && (
                <div className={s.files}>
                  {Object.entries(connector.files).map(([file, text]) => (
                    <details key={file} open={file.endsWith(".xml")}>
                      <summary>
                        {file}
                        <button
                          className={s.ghost}
                          onClick={(e) => {
                            e.preventDefault();
                            save(file, text);
                          }}
                          aria-label={`Download ${file}`}
                        >
                          <Download size={14} />
                        </button>
                      </summary>
                      <pre>{text}</pre>
                    </details>
                  ))}
                </div>
              )}
            </>
          )}
        </aside>
      </div>
    </section>
  );
}
