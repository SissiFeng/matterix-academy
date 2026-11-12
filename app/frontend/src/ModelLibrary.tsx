import { ArrowLeft, Box, Plus, Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { api, json } from "./api";
import { looseModel } from "./instrumentModels";
import type {
  InstrumentCatalog,
  Mesh,
  ModelEntry,
  ModelResults,
  Operation,
} from "./instrumentTypes";
import { aim, lit, thumbnail, upright } from "./modelViews";
import s from "./ModelLibrary.module.css";

const sources = {
  workcell: "Workcell model",
  chemlab: "ChemLab · NC",
  simready: "SimReady",
} as const;
const can: Record<Operation, string> = {
  load: "Load",
  transfer: "Transfer",
  mix: "Mix",
  heat: "Heat",
  read: "Read",
  wait: "Wait",
};
const STACKED = "(max-width: 980px)";
const metres = (size: number[]) =>
  `${size.map((v) => v.toFixed(2)).join(" × ")} m`;

/** Every instrument with a 3D model, to browse before adding one to a workcell. */
export default function ModelLibrary({
  canAdd,
  onAdded,
  onPlan,
}: {
  canAdd: boolean;
  onAdded: () => void;
  onPlan: () => void;
}) {
  const [query, setQuery] = useState("");
  const [domain, setDomain] = useState("");
  const [found, setFound] = useState<ModelResults | null>(null);
  const [selected, setSelected] = useState<ModelEntry | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const detail = useRef<HTMLElement>(null);

  useEffect(() => {
    let current = true;
    const params = new URLSearchParams({ q: query.trim(), domain });
    const timer = window.setTimeout(
      () =>
        api<ModelResults>(`/twins/library/models?${params}`)
          .then((page) => {
            if (!current) return;
            setFound(page);
            // Side by side, the first model fills the preview; stacked, it waits for a tap.
            if (!window.matchMedia(STACKED).matches)
              setSelected((was) => was ?? page.results[0] ?? null);
          })
          .catch((e) => current && setError((e as Error).message)),
      query ? 200 : 0,
    );
    return () => {
      current = false;
      window.clearTimeout(timer);
    };
  }, [query, domain]);

  const more = async () => {
    if (!found) return;
    const params = new URLSearchParams({
      q: query.trim(),
      domain,
      offset: String(found.results.length),
    });
    try {
      const page = await api<ModelResults>(`/twins/library/models?${params}`);
      setFound({ ...page, results: [...found.results, ...page.results] });
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const add = async (entry: ModelEntry) => {
    setBusy(true);
    setError("");
    try {
      const { version } = await api<InstrumentCatalog>("/twins");
      await api<InstrumentCatalog>(
        "/twins",
        json({
          id: crypto.randomUUID(),
          expected_version: version,
          [`${entry.collection}_id`]: entry.id,
        }),
      );
      onAdded();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const choose = (entry: ModelEntry) => {
    setSelected(entry);
    if (window.matchMedia(STACKED).matches)
      requestAnimationFrame(() =>
        detail.current?.scrollIntoView({ behavior: "smooth", block: "start" }),
      );
  };
  const domains = found ? Object.entries(found.domains) : [];
  const all = domains.reduce((n, [, count]) => n + count, 0);

  return (
    <section className={s.page} aria-labelledby="model-library">
      <header className={s.heading}>
        <h2 id="model-library">Instrument models</h2>
        <button className={s.planLink} onClick={onPlan}>
          <ArrowLeft size={15} aria-hidden /> Back to instruments
        </button>
      </header>
      {error && (
        <p className={s.alert} role="alert">
          {error}
        </p>
      )}
      <div className={s.layout}>
        <div className={s.browse}>
          <div className={s.filters}>
            <label className={s.search}>
              <Search size={16} aria-hidden />
              <input
                type="search"
                value={query}
                placeholder={`Search ${found?.size ?? ""} models`}
                aria-label="Search instrument models"
                onChange={(e) => setQuery(e.target.value)}
              />
            </label>
            <select
              className={s.domain}
              aria-label="Domain"
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
            >
              <option value="">All domains · {all}</option>
              {domains.map(([name, count]) => (
                <option key={name} value={name}>
                  {name} · {count}
                </option>
              ))}
              {domain && !found?.domains[domain] && (
                <option value={domain}>{domain} · 0</option>
              )}
            </select>
          </div>
          {found && found.total === 0 ? (
            <p className={s.empty}>
              No model matches. Try a maker or instrument type, or clear the
              domain.
            </p>
          ) : (
            <ul className={s.grid} aria-label="Models">
              {found?.results.map((entry) => (
                <li key={`${entry.collection}:${entry.id}`}>
                  <button
                    className={s.card}
                    aria-pressed={selected?.id === entry.id}
                    onClick={() => choose(entry)}
                  >
                    <Thumbnail mesh={entry.mesh} />
                    <strong>{entry.name}</strong>
                    <small>
                      {entry.provider} · {metres(entry.size_m)}
                    </small>
                    <span
                      className={s.source}
                      data-collection={entry.collection}
                    >
                      {sources[entry.collection]}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {found && found.results.length < found.total && (
            <button className={s.more} onClick={more}>
              Show more · {found.total - found.results.length} left
            </button>
          )}
        </div>
        {selected && (
          <aside ref={detail} className={s.detail} aria-label={selected.name}>
            <Preview mesh={selected.mesh} />
            <div className={s.facts}>
              <h3>{selected.name}</h3>
              <p>{selected.label}</p>
              <dl>
                <dt>Provided by</dt>
                <dd>{selected.provider}</dd>
                <dt>Size</dt>
                <dd>{metres(selected.size_m)} · w × d × h</dd>
                <dt>Domain</dt>
                <dd>{selected.domain}</dd>
                <dt>Teaching operations</dt>
                <dd>{selected.operations.map((o) => can[o]).join(", ")}</dd>
                <dt>License</dt>
                <dd>{selected.license}</dd>
              </dl>
              <button
                className={s.add}
                disabled={!canAdd || busy}
                onClick={() => add(selected)}
              >
                <Plus size={16} aria-hidden /> Add to my workcell
              </button>
              {!canAdd && (
                <p className={s.reason}>
                  Adding instruments is open to researchers.
                </p>
              )}
              <details className={s.about}>
                <summary>Source and limits</summary>
                <p>
                  <a href={selected.url} target="_blank" rel="noreferrer">
                    {selected.attribution}
                  </a>
                </p>
                <p>
                  A reconstruction for teaching, not manufacturer CAD.
                  Operations, volume and limits are defaults to correct before
                  confirming.
                  {selected.license === "CC-BY-NC-4.0" &&
                    " Non-commercial use only."}
                </p>
              </details>
            </div>
          </aside>
        )}
      </div>
    </section>
  );
}

/** Drawn when the card scrolls into view; a box icon stands in until then. */
function Thumbnail({ mesh }: { mesh: Mesh }) {
  const host = useRef<HTMLSpanElement>(null);
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let alive = true;
    const observer = new IntersectionObserver(
      ([seen]) => {
        if (!seen.isIntersecting) return;
        observer.disconnect();
        thumbnail(mesh).then((url) => {
          if (!alive) return;
          if (url) setSrc(url);
          else setFailed(true);
        });
      },
      { rootMargin: "200px" },
    );
    observer.observe(el);
    return () => {
      alive = false;
      observer.disconnect();
    };
  }, [mesh]);
  return (
    <span ref={host} className={s.thumb} data-failed={failed || undefined}>
      {src ? <img src={src} alt="" /> : <Box size={22} aria-hidden />}
    </span>
  );
}

function Preview({ mesh }: { mesh: Mesh }) {
  const host = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<"loading" | "ready" | "failed">("loading");
  const key = mesh.url ?? mesh.kind;
  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let alive = true;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      setState("failed");
      return;
    }
    setState("loading");
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    lit(scene);
    const floor = new THREE.GridHelper(2, 20, 0x6f8a78, 0x3a4c42);
    scene.add(floor);
    const camera = new THREE.PerspectiveCamera(32, 1, 0.01, 50);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    let model: Awaited<ReturnType<typeof looseModel>> | null = null;
    let holder: THREE.Object3D | null = null;
    const resize = () => {
      const { width, height } = el.getBoundingClientRect();
      renderer.setSize(width, height, false);
      if (holder)
        controls.target.copy(
          aim(camera, holder, Math.max(1, width) / Math.max(1, height)),
        );
      controls.update();
    };
    looseModel(mesh)
      .then((loaded) => {
        if (!alive) return loaded.release();
        model = loaded;
        holder = upright(loaded.object, mesh.up);
        scene.add(holder);
        const size = new THREE.Box3()
          .setFromObject(holder)
          .getSize(new THREE.Vector3());
        floor.scale.setScalar(Math.max(size.x, size.z) * 0.9);
        resize();
        setState("ready");
      })
      .catch((e) => {
        console.warn((e as Error).message);
        if (alive) setState("failed");
      });
    const observer = new ResizeObserver(resize);
    observer.observe(el);
    let frame = 0;
    const tick = () => {
      controls.update();
      renderer.render(scene, camera);
      frame = requestAnimationFrame(tick);
    };
    tick();
    return () => {
      alive = false;
      cancelAnimationFrame(frame);
      observer.disconnect();
      controls.dispose();
      model?.release();
      floor.geometry.dispose();
      (floor.material as THREE.Material).dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
    // `key` identifies the model; the mesh object changes identity on every page fetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return (
    <div className={s.preview} data-state={state}>
      <div ref={host} className={s.canvas} />
      {state === "loading" && <span className={s.status}>Loading model…</span>}
      {state === "failed" && (
        <span className={s.status} role="status">
          The 3D model could not be loaded.
        </span>
      )}
    </div>
  );
}
