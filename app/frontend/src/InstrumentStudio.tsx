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
  ArrowRight,
  ArrowUp,
  Camera,
  Download,
  Play,
  Plug,
  Plus,
  Search,
  Trash2,
} from "lucide-react";
import { api, apiText, apiBlob, ApiError, json } from "./api";
import {
  operationLabels,
  type ConnectorPackage,
  type InstrumentCatalog,
  type Layout,
  type LibraryEntry,
  type LibraryResults,
  type LayoutPreview,
  type LayoutSearchChunk,
  type BriefRole,
  type Operation,
  type Step,
  type Twin,
  DEFAULT_SAMPLE,
  siteKeys,
} from "./instrumentTypes";
import BriefPanel, { RoleBindings, applyBlocker } from "./BriefPanel";
import s from "./InstrumentStudio.module.css";
import LayoutPanel from "./LayoutPanel";
import { LIBRARY_QUERY_KEY } from "./LessonSearch";
import { conflicts, defaultLayout } from "./layoutGeometry";
import TwinCard from "./TwinCard";

const TwinScene = lazy(() => import("./TwinScene"));
type Tab = "describe" | "instruments" | "workflow" | "layout" | "connectors";
const tabs: { id: Tab; label: string }[] = [
  { id: "describe", label: "1 · Describe" },
  { id: "instruments", label: "2 · Instruments" },
  { id: "workflow", label: "3 · Workflow" },
  { id: "layout", label: "4 · Layout" },
  { id: "connectors", label: "5 · Connectors" },
];
const templateLabels: Record<string, string> = {
  "liquid-handler": "Liquid handler",
  heater: "Heating station",
  reader: "Plate reader",
  "transfer-arm": "Transfer robot",
};
/** Search chunks spent finding a first layout the arm can serve. */
const START_CHUNKS = 3;
const collectionLabels = {
  workcell: "Workcell model",
  chemlab: "ChemLab · NC",
  simready: "SimReady",
} as const;
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
  saveBlob(name, new Blob([text], { type: "text/plain" }));
}
function saveBlob(name: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const link = Object.assign(document.createElement("a"), {
    href: url,
    download: name,
  });
  link.click();
  URL.revokeObjectURL(url);
}

export default function InstrumentStudio({
  registerLeaveGuard,
}: {
  registerLeaveGuard: (guard: (() => boolean) | null) => void;
}) {
  const [catalog, setCatalog] = useState<InstrumentCatalog | null>(null);
  const [tab, setTab] = useState<Tab>(() => {
    const section = window.location.hash.split("/")[2];
    return tabs.find((t) => t.id === section)?.id ?? "describe";
  });
  /** The drafted role the next added instrument is chosen for. */
  const [finding, setFinding] = useState<string | null>(null);
  const [steps, setSteps] = useState<Step[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [frame, setFrame] = useState(-1);
  const [connector, setConnector] = useState<ConnectorPackage | null>(null);
  const version = useRef(0);
  const dirty = useRef(false);
  const editRevision = useRef(0);
  const twinDirty = useRef(new Set<string>());
  const [layoutDraft, setLayoutDraft] = useState<Layout | null>(null);
  const layoutDirty = useRef(false);
  const layoutRevision = useRef(0);
  const [preview, setPreview] = useState<LayoutPreview | null>(null);
  const [checking, setChecking] = useState(false);
  const [selectedMotion, setSelectedMotion] = useState(0);
  const [armFrame, setArmFrame] = useState(0);
  // A search started on Meet the instruments carries over once.
  const [query, setQuery] = useState(() => {
    try {
      const carried = sessionStorage.getItem(LIBRARY_QUERY_KEY) ?? "";
      sessionStorage.removeItem(LIBRARY_QUERY_KEY);
      return carried;
    } catch {
      return "";
    }
  });
  const [library, setLibrary] = useState<LibraryResults | null>(null);
  const trackTwinDirty = useCallback((id: string, changed: boolean) => {
    if (changed) twinDirty.current.add(id);
    else twinDirty.current.delete(id);
  }, []);
  useEffect(() => {
    const unsaved = () =>
      dirty.current || layoutDirty.current || twinDirty.current.size > 0;
    registerLeaveGuard(
      () =>
        !unsaved() ||
        window.confirm(
          "Your instrument, layout or workflow changes are not saved. Leave this workspace?",
        ),
    );
    const warn = (event: BeforeUnloadEvent) => {
      if (unsaved()) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", warn);
    return () => {
      registerLeaveGuard(null);
      window.removeEventListener("beforeunload", warn);
    };
  }, [registerLeaveGuard]);

  const accept = useCallback((next: InstrumentCatalog) => {
    if (next.version < version.current) return;
    version.current = next.version;
    setCatalog(next);
    if (!dirty.current) setSteps(next.steps);
    if (!layoutDirty.current) setLayoutDraft(next.layout ?? null);
  }, []);
  const load = useCallback(
    async () => accept(await api<InstrumentCatalog>("/twins")),
    [accept],
  );
  useEffect(() => {
    load().catch((e) => setError((e as Error).message));
  }, [load]);

  /** Adds a twin and, when a drafted role is being filled, chooses it for that role. */
  const addTwin = async (id: string, source: object) => {
    const added = await mutate("/twins", { id, ...source });
    if (added && finding) {
      await mutate(
        "/twins/workflow/brief/bind",
        { role: finding, twin_id: id },
        "PUT",
      );
      setFinding(null);
    }
    return added;
  };
  const mutate = async (path: string, body: object, method = "POST") => {
    setBusy(true);
    setError("");
    try {
      const next = await api<InstrumentCatalog>(
        path,
        json({ expected_version: version.current, ...body }, method),
      );
      accept(next);
      return next;
    } catch (e) {
      setError((e as Error).message);
      // Reconcile lost receipts by reading; never repeat a mutation automatically.
      if (!(e instanceof ApiError) || e.status === 409 || e.status >= 500)
        await load().catch(() => undefined);
      return false;
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    let current = true;
    const timer = window.setTimeout(
      () =>
        api<LibraryResults>(
          // Every match is listed for the learner to pick from; the list scrolls.
          `/twins/library?q=${encodeURIComponent(query.trim())}&limit=300`,
        )
          .then((found) => current && setLibrary(found))
          .catch((e) => current && setError((e as Error).message)),
      query ? 200 : 0,
    );
    return () => {
      current = false;
      window.clearTimeout(timer);
    };
  }, [query]);
  const addFromLibrary = async (entry: LibraryEntry) => {
    const id = crypto.randomUUID();
    const added = await addTwin(id, {
      [`${entry.collection}_id`]: entry.id,
    });
    // The draft lands below the library; bring it into view for review.
    if (added)
      requestAnimationFrame(() =>
        document
          .querySelector(`[data-twin="${id}"]`)
          ?.scrollIntoView({ behavior: "smooth", block: "start" }),
      );
  };

  const generating = catalog?.twins.find((t) => t.status === "generating");
  const drafting = catalog?.brief?.status === "generating";
  useEffect(() => {
    if (!drafting) return;
    const timer = window.setInterval(async () => {
      try {
        accept(
          await api<InstrumentCatalog>(
            "/twins/workflow/brief/poll",
            json({ expected_version: version.current }),
          ),
        );
      } catch (e) {
        if (e instanceof ApiError && e.status === 409)
          load().catch(() => undefined);
        else setError((e as Error).message);
      }
    }, 2500);
    return () => window.clearInterval(timer);
  }, [drafting, accept, load]);
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

  const confirmed = catalog?.twins.filter((t) => t.confirmed) ?? [];
  const confirmedIds = new Set(confirmed.map((t) => t.id));
  const specs = new Map(confirmed.map((t) => [t.id, t.spec!]));
  const baseLayout = layoutDraft ?? defaultLayout(confirmed);
  // Drop placements of instruments that were removed or are no longer confirmed.
  const draft: Layout = {
    ...baseLayout,
    placements: baseLayout.placements.filter((p) =>
      confirmedIds.has(p.twin_id),
    ),
  };
  const draftKey =
    tab === "layout" && draft.placements.length ? JSON.stringify(draft) : "";
  const localConflict = draftKey ? conflicts(draft, specs).size > 0 : false;
  useEffect(() => {
    if (!draftKey || localConflict) {
      setPreview(null);
      return;
    }
    let live = true;
    setChecking(true);
    // Debounced so a drag is checked once it settles.
    const timer = window.setTimeout(async () => {
      try {
        const result = await api<LayoutPreview>(
          "/twins/layout/preview",
          json(JSON.parse(draftKey)),
        );
        if (live) {
          setPreview(result);
          setSelectedMotion(result.blocked ? result.motions.length : 0);
        }
      } catch (e) {
        if (live) setError((e as Error).message);
      } finally {
        if (live) setChecking(false);
      }
    }, 350);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [draftKey, localConflict, catalog?.version]);
  // A first layout the arm cannot serve is replaced by the quickest one a short search
  // finds; it stays an unsaved draft to adjust and save.
  const [starting, setStarting] = useState<"searching" | "none" | null>(null);
  const startTried = useRef("");
  const startKey =
    tab === "layout" &&
    !catalog?.layout &&
    !layoutDraft &&
    preview?.error &&
    catalog?.steps.some((step) => step.operation === "transfer")
      ? JSON.stringify([draft, catalog.steps])
      : "";
  useEffect(() => {
    if (!startKey || startTried.current === startKey) return;
    startTried.current = startKey;
    const [first] = JSON.parse(startKey) as [Layout];
    let live = true;
    setStarting("searching");
    (async () => {
      let start: number | null = 0;
      for (let chunks = 0; chunks < START_CHUNKS && start !== null; chunks++) {
        const chunk: LayoutSearchChunk = await api<LayoutSearchChunk>(
          "/twins/layout/search",
          json({ bench: first.bench, fixed: [], start, avoid: [] }),
        );
        if (!live) return;
        if (chunk.candidates.length) {
          const best = chunk.candidates.reduce((a, b) =>
            b.run_s < a.run_s ? b : a,
          );
          layoutDirty.current = true;
          layoutRevision.current += 1;
          setLayoutDraft(best.layout);
          setStarting(null);
          return;
        }
        start = chunk.next;
      }
      setStarting("none");
    })().catch(() => live && setStarting(null));
    return () => {
      live = false;
      setStarting(null);
    };
  }, [startKey]);
  const selected =
    tab === "layout" && preview
      ? ([...preview.motions, ...(preview.blocked ? [preview.blocked] : [])][
          selectedMotion
        ] ?? null)
      : null;
  const motionFrames = selected?.frames ?? null;
  useEffect(() => {
    setArmFrame(0);
    if (!motionFrames?.length) return;
    // Loop the path with a short hold on the final pose.
    const timer = window.setInterval(
      () => setArmFrame((f) => (f + 1) % (motionFrames.length + 15)),
      70,
    );
    return () => window.clearInterval(timer);
  }, [motionFrames]);

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

  const stations = confirmed.filter((t) => t.spec!.operations.includes("load"));
  const replayTwins = run?.twins.every((t) => t.spec)
    ? run.twins.map((t) => ({
        id: t.id,
        spec: t.spec!,
        confirmed: true,
        asset: catalog.twins.find((c) => c.id === t.id)?.asset,
      }))
    : confirmed;
  const savedPlaced = new Set(catalog.layout?.placements.map((p) => p.twin_id));
  const savedLayout = (shown: { id: string }[]) =>
    catalog.layout && shown.every((t) => savedPlaced.has(t.id))
      ? catalog.layout
      : null;
  const blockedTwin =
    tab === "layout" && preview?.blocked
      ? (confirmed.find((t) => t.spec!.name === preview.blocked!.blocked_by)
          ?.id ?? null)
      : null;
  const showingBlocked =
    !!preview?.blocked && selectedMotion === preview.motions.length;
  const editLayout = (next: Layout) => {
    layoutDirty.current = true;
    layoutRevision.current += 1;
    setLayoutDraft(next);
  };
  const name = (id: string | null) =>
    (tab === "workflow" ? run?.twins.find((t) => t.id === id)?.name : null) ??
    catalog.twins.find((t) => t.id === id)?.spec?.name ??
    "—";
  const editSteps = (next: Step[]) => {
    dirty.current = true;
    editRevision.current += 1;
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
  const go = (next: Tab) => {
    setTab(next);
    window.history.replaceState({}, "", `/#/plan/${next}`);
  };
  const findFor = (role: BriefRole) => {
    setFinding((current) => (current === role.key ? null : role.key));
    setQuery(role.query);
    requestAnimationFrame(() =>
      document
        .querySelector('[aria-label="Asset library"]')
        ?.scrollIntoView({ behavior: "smooth", block: "start" }),
    );
  };
  const fillBlocker = applyBlocker(catalog.brief, catalog.twins);
  const trace =
    run && frame >= 0 ? run.trace[Math.min(frame, run.trace.length - 1)] : null;

  return (
    <section className={s.page} aria-labelledby="byo-instrument">
      <div className={s.heading}>
        <div>
          <h2 id="byo-instrument">Plan your workcell</h2>
          <p>
            Describe the workflow, choose each instrument, then find a bench
            layout that runs it.
          </p>
        </div>
      </div>
      <p className={s.notice}>
        Synthetic teaching twins: runs and arm paths are not Isaac/GPU, physical
        robot or chemical validation.
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
            onClick={() => {
              if (
                t.id !== tab &&
                twinDirty.current.size &&
                !window.confirm(
                  "Your instrument edits are not saved. Discard them and switch tabs?",
                )
              )
                return;
              go(t.id);
            }}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className={s.workspace}>
        <section className={s.viewport} aria-label="Workcell preview">
          <div className={s.viewportBar}>
            <span>
              {tab === "layout"
                ? motionFrames
                  ? `${showingBlocked ? "Blocked attempt" : "Planned path"} · Step ${(showingBlocked ? preview!.blocked! : preview!.motions[selectedMotion]).step} · drag to orbit`
                  : `${draft.placements.length} on the bench · drag to orbit`
                : trace
                  ? `Last run · Step ${trace.step} · ${operationLabels[trace.operation]} · ${name(trace.device_id)}`
                  : `${catalog.twins.length} instrument${catalog.twins.length === 1 ? "" : "s"} · drag to orbit`}
            </span>
            <span>SYNTHETIC TWIN</span>
          </div>
          <Suspense fallback={<div className={s.scene} />}>
            <TwinScene
              twins={
                tab === "instruments" || tab === "describe"
                  ? catalog.twins
                  : tab === "workflow"
                    ? replayTwins
                    : confirmed
              }
              active={tab === "workflow" ? trace?.device_id : null}
              sample={tab === "workflow" ? trace?.location : null}
              layout={
                tab === "layout"
                  ? draft
                  : tab === "workflow"
                    ? savedLayout(replayTwins)
                    : tab === "connectors"
                      ? savedLayout(confirmed)
                      : null
              }
              arm={
                motionFrames?.length
                  ? motionFrames[Math.min(armFrame, motionFrames.length - 1)]
                  : null
              }
              armJoints={
                selected?.joints?.length
                  ? selected.joints[
                      Math.min(armFrame, selected.joints.length - 1)
                    ]
                  : null
              }
              armActor={selected?.actor_id ?? null}
              path={motionFrames?.map((f) => f[f.length - 1]) ?? null}
              blocked={showingBlocked ? blockedTwin : null}
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
          {tab === "describe" && (
            <BriefPanel
              catalog={catalog}
              busy={busy}
              onDescribe={(text) => mutate("/twins/workflow/brief", { text })}
              onImport={(name, draft) =>
                mutate("/twins/workflow/brief/import", { name, draft })
              }
              onSchema={async () => {
                try {
                  const doc = await apiText("/twins/workflow/brief/schema");
                  saveBlob(
                    "academy-workflow-draft.schema.json",
                    new Blob([doc], { type: "application/json" }),
                  );
                } catch (e) {
                  setError((e as Error).message);
                }
              }}
              onNext={() => go("instruments")}
            />
          )}

          {tab === "instruments" && (
            <>
              {catalog.brief?.draft && (
                <RoleBindings
                  brief={catalog.brief}
                  twins={catalog.twins}
                  busy={busy}
                  finding={finding}
                  onBind={(role, twinId) =>
                    mutate(
                      "/twins/workflow/brief/bind",
                      { role, twin_id: twinId },
                      "PUT",
                    )
                  }
                  onFind={findFor}
                  onChoose={() =>
                    mutate("/twins/workflow/brief/choose", {}, "PUT")
                  }
                  onAccept={async () => {
                    // Unsaved step edits stay protected until the draft has replaced them.
                    const next = await mutate(
                      "/twins/workflow/brief/accept",
                      {},
                      "PUT",
                    );
                    if (next) {
                      // A response older than the catalog on the page was not applied.
                      if (next.version === version.current) {
                        dirty.current = false;
                        setSteps(next.steps);
                      }
                      go("workflow");
                    }
                  }}
                />
              )}
              <div className={s.addHeading}>
                <h2>Add an instrument</h2>
                <a className={s.modelsLink} href="#/models">
                  Browse models <ArrowRight size={14} aria-hidden />
                </a>
              </div>
              <section className={s.library} aria-label="Asset library">
                <label className={s.search}>
                  <Search size={16} aria-hidden />
                  <input
                    type="search"
                    value={query}
                    placeholder={`Search ${library?.size ?? ""} instruments`}
                    aria-label="Search the asset library"
                    onChange={(e) => setQuery(e.target.value)}
                  />
                </label>
                <p className={s.libraryMeta}>
                  {query.trim()
                    ? `${library?.total ?? 0} match${library?.total === 1 ? "" : "es"}`
                    : "Featured · search a model, or a purpose such as mix or weigh"}
                </p>
                <ul className={s.results}>
                  {library?.results.map((entry) => (
                    <li key={`${entry.collection}:${entry.id}`}>
                      <button
                        className={s.libraryItem}
                        disabled={busy}
                        title={entry.attribution}
                        aria-label={`Add ${entry.name}`}
                        onClick={() => addFromLibrary(entry)}
                      >
                        <span>
                          <strong>{entry.name}</strong>
                          <small>
                            {entry.size_m.map((v) => v.toFixed(2)).join(" × ")}{" "}
                            m · {entry.label}
                          </small>
                        </span>
                        <span
                          className={s.source}
                          data-collection={entry.collection}
                        >
                          {collectionLabels[entry.collection]}
                        </span>
                        <Plus size={14} aria-hidden />
                      </button>
                    </li>
                  ))}
                </ul>
                {query.trim() && library?.total === 0 && (
                  <p className={s.muted}>
                    Not in the library. Photograph it or start from a generic
                    template below.
                  </p>
                )}
                <p className={s.footnote}>
                  Workcell and ChemLab entries are drawn with their 3D model;
                  SimReady entries show their footprint. Operations, volume and
                  limits are teaching defaults to correct before confirming.
                  ChemLab-Assets entries are CC-BY-NC-4.0, non-commercial use
                  only.
                </p>
              </section>
              <h3 className={s.fallbackTitle}>
                Not sure of the model, or not listed?
              </h3>
              <label
                className={`${s.upload} ${!catalog.astra_available ? s.disabled : ""}`}
              >
                <Camera size={18} />
                <span>
                  <strong>Upload a photo</strong>
                  <small>
                    {catalog.astra_available
                      ? "PNG, JPEG or WebP · GPT-6 Astra matches it to the library and sketches a draft"
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
                      await addTwin(crypto.randomUUID(), {
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
                      addTwin(crypto.randomUUID(), { template_id: id })
                    }
                  >
                    <Plus size={14} /> {templateLabels[id] ?? id}
                  </button>
                ))}
              </div>
              {catalog.twins.length === 0 && (
                <p className={s.muted}>
                  No instruments yet. Add one from the library, a photo or a
                  template to start your workcell.
                </p>
              )}
              {catalog.twins.map((twin) => (
                <TwinCard
                  key={twin.id}
                  twin={twin}
                  busy={busy}
                  onDirtyChange={trackTwinDirty}
                  onConfirm={(spec) =>
                    mutate(`/twins/${twin.id}/confirm`, { spec }, "PUT")
                  }
                  onRemove={() => mutate(`/twins/${twin.id}`, {}, "DELETE")}
                  onResidual={(input) =>
                    mutate(`/twins/${twin.id}/residuals`, input).then(Boolean)
                  }
                  onSizeCheck={(checked) =>
                    mutate(`/twins/${twin.id}/size-check`, { checked }, "PUT")
                  }
                  onMatch={(m) =>
                    mutate(
                      `/twins/${twin.id}/match`,
                      { collection: m.collection, asset_id: m.id },
                      "PUT",
                    )
                  }
                  onDownload={async () => {
                    try {
                      save(
                        `${twin.spec!.name}.usda`,
                        await apiText(`/twins/${twin.id}/usd`),
                      );
                    } catch (e) {
                      setError((e as Error).message);
                    }
                  }}
                />
              ))}
            </>
          )}

          {tab === "layout" &&
            (confirmed.length === 0 ? (
              <>
                <h2>Lay out the bench</h2>
                <p className={s.muted}>
                  Confirm at least one instrument first.
                </p>
              </>
            ) : (
              <>
                {starting && (
                  <p className={s.starting} role="status">
                    {starting === "searching"
                      ? "The arm cannot serve this first arrangement. Finding one it can…"
                      : "No layout the arm can serve turned up yet. Search layouts tries more, or move instruments closer."}
                  </p>
                )}
                <LayoutPanel
                  twins={confirmed}
                  layout={draft}
                  onChange={editLayout}
                  preview={preview}
                  checking={checking}
                  selectedMotion={selectedMotion}
                  onSelectMotion={(i) => setSelectedMotion(i)}
                  saveDisabled={
                    busy || (!layoutDirty.current && !!catalog.layout)
                  }
                  onExport={
                    catalog.layout &&
                    !layoutDirty.current &&
                    !localConflict &&
                    preview &&
                    !preview.error
                      ? async (step, speed) => {
                          try {
                            const doc = await apiText(
                              `/twins/layout/action-chain?step=${step}&speed=${speed}`,
                            );
                            saveBlob(
                              `ur5e-action-chain-step-${step}.json`,
                              new Blob([doc], { type: "application/json" }),
                            );
                          } catch (e) {
                            setError((e as Error).message);
                          }
                        }
                      : undefined
                  }
                  onSearch={(fixed, start, avoid) =>
                    api<LayoutSearchChunk>(
                      "/twins/layout/search",
                      json({ bench: draft.bench, fixed, start, avoid }),
                    )
                  }
                  constraints={catalog.constraints ?? []}
                  onConstraints={(next) =>
                    mutate(
                      "/twins/layout/constraints",
                      { constraints: next },
                      "PUT",
                    )
                  }
                  busy={busy}
                  onSave={async () => {
                    const submitted = layoutRevision.current;
                    if (await mutate("/twins/layout", draft, "PUT"))
                      if (layoutRevision.current === submitted)
                        layoutDirty.current = false;
                  }}
                />
              </>
            ))}
          {tab === "layout" && (
            <a className={s.modelsLink} href="#/models">
              Browse instrument models <ArrowRight size={14} aria-hidden />
            </a>
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
                  {catalog.brief?.draft && (
                    <div className={s.fill}>
                      <button
                        className={s.secondary}
                        disabled={busy || !!fillBlocker}
                        onClick={() => {
                          if (
                            (dirty.current || catalog.steps.length > 0) &&
                            !window.confirm(
                              "Replace the current steps with the drafted ones?",
                            )
                          )
                            return;
                          dirty.current = false;
                          mutate("/twins/workflow/brief/apply", {}, "PUT");
                        }}
                      >
                        Use drafted steps
                      </button>
                      {fillBlocker && <small>{fillBlocker}</small>}
                    </div>
                  )}
                  <p className={s.muted}>
                    Load each plate once, transfer it between stations, and act
                    on it where it is.
                    {catalog.layout &&
                      " Transfers must also have a collision-free arm path on the saved bench layout."}
                  </p>
                  <datalist id="workflow-samples">
                    {[
                      ...new Set([
                        DEFAULT_SAMPLE,
                        ...steps.map((x) => x.sample ?? DEFAULT_SAMPLE),
                      ]),
                    ].map((name) => (
                      <option key={name} value={name} />
                    ))}
                  </datalist>
                  <ol className={s.steps}>
                    {steps.map((step, i) => {
                      const device = confirmed.find(
                        (t) => t.id === step.device_id,
                      );
                      const replace = (next: Step) =>
                        editSteps(
                          steps.map((x, j) =>
                            j === i
                              ? { ...next, sample: next.sample ?? step.sample }
                              : x,
                          ),
                        );
                      // A slot is worth choosing only where there is more than one.
                      const slotTwin =
                        step.operation === "load"
                          ? device
                          : step.operation === "transfer"
                            ? confirmed.find((t) => t.id === step.target_id)
                            : undefined;
                      const slots = slotTwin ? siteKeys(slotTwin.spec!) : [];
                      const slotField =
                        step.operation === "load" ? "site" : "target_site";
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
                            {step.operation !== "wait" && (
                              <input
                                className={s.sample}
                                list="workflow-samples"
                                aria-label={`Step ${i + 1} sample`}
                                value={step.sample ?? DEFAULT_SAMPLE}
                                maxLength={24}
                                onChange={(e) =>
                                  replace({
                                    ...step,
                                    sample:
                                      e.target.value
                                        .toLowerCase()
                                        .replace(/[^a-z0-9-]/g, "-") ||
                                      DEFAULT_SAMPLE,
                                  })
                                }
                              />
                            )}
                            {slots.length > 1 && (
                              <select
                                aria-label={`Step ${i + 1} slot`}
                                value={step[slotField] ?? ""}
                                onChange={(e) =>
                                  replace({
                                    ...step,
                                    [slotField]: e.target.value,
                                  })
                                }
                              >
                                <option value="">Any free slot</option>
                                {slots.map((key) => (
                                  <option key={key} value={key}>
                                    Slot {key}
                                  </option>
                                ))}
                              </select>
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
                        const submittedRevision = editRevision.current;
                        if (await mutate("/twins/workflow", { steps }, "PUT")) {
                          if (editRevision.current === submittedRevision) {
                            dirty.current = false;
                            setSteps([...steps]);
                          }
                        }
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
                            {t.motion &&
                              ` · ${t.motion.arm} path ${t.motion.length_m.toFixed(2)} m, ${(t.motion.clearance_m * 100).toFixed(1)} cm clearance`}
                          </li>
                        ))}
                      </ol>
                      <small>
                        Synthetic · in-process mock contract · teaching state
                        only
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
                        <strong>Mock command contract</strong>
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
                          saveBlob(
                            `mock-workcell-${twin.id}.zip`,
                            await apiBlob(`/twins/${twin.id}/sila.zip`),
                          );
                        } catch (e) {
                          setError((e as Error).message);
                        }
                      }}
                    >
                      <Download size={15} /> Download runnable SiLA bundle
                    </button>
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
