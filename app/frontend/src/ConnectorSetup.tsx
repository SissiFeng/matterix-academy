import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Circle,
  Copy,
  Download,
  Laptop,
  Link2,
  RefreshCw,
  ShieldCheck,
  Square,
  Unplug,
} from "lucide-react";
import { api, ApiError, json } from "./api";
import type { Session } from "./types";
import type {
  ConnectorCatalog,
  ConnectorInstrument,
  ConnectorPlatform,
  ConnectorPreflight,
  InstrumentConnection,
  PhysicalRun,
} from "./connectorTypes";
import s from "./ConnectorSetup.module.css";

const modelName = (model: ConnectorInstrument) =>
  model === "flex" ? "Opentrons Flex" : "Opentrons OT-2";
const platformName = {
  macos: "macOS",
  linux: "Ubuntu / Linux",
  windows: "Windows",
};
const refKey = (id: string) => `academy-physical-run-v1:${id}`;
const workflowKey = (id: string) => `academy-connector-workflow-v1:${id}`;
const isFinal = (run: PhysicalRun | null) =>
  !!run && ["completed", "failed", "stopped"].includes(run.status);
function hasBoundResolution(run: PhysicalRun | null): boolean {
  const audit = run?.resolution;
  const request = audit?.request;
  return !!(
    run?.status === "unknown" &&
    audit?.historical_status === "unknown" &&
    audit.replay_authorized === false &&
    Number.isFinite(audit.resolved_at) &&
    audit.resolved_at > 0 &&
    request &&
    /^[a-f0-9-]{36}$/.test(request.resolution_id) &&
    /^[a-f0-9-]{36}$/.test(request.installation_id) &&
    Number.isInteger(request.expected_version) &&
    request.expected_version >= 1 &&
    request.expected_version < run.version &&
    request.connection_id === run.connection_id &&
    request.plan_hash === run.plan_hash &&
    request.instrument === run.instrument &&
    request.stopped === true &&
    request.released === true &&
    (request.no_run_created === true
      ? request.robot_run_id === null
      : request.no_run_created === false &&
        !!request.protocol_id &&
        !!request.robot_run_id) &&
    /^[a-f0-9]{64}$/.test(request.evidence_sha256) &&
    typeof request.operator_id === "string" &&
    request.operator_id.trim()
  );
}
const messageOf = (error: unknown) =>
  error instanceof Error
    ? error.message
    : "The request could not be completed.";

function pendingRunId(id: string): string | null {
  try {
    const value = sessionStorage.getItem(refKey(id));
    return value && /^[a-f0-9-]{36}$/.test(value) ? value : null;
  } catch {
    return null;
  }
}

function savedWorkflowId(id: string): string {
  try {
    const value = sessionStorage.getItem(workflowKey(id));
    return value && /^[a-f0-9-]{36}$/.test(value) ? value : "";
  } catch {
    return "";
  }
}

export default function ConnectorSetup({
  initialSessionId,
  onOpen,
  onBack,
}: {
  initialSessionId?: string;
  onOpen: (session: Session) => void;
  onBack: () => void;
}) {
  const [catalog, setCatalog] = useState<ConnectorCatalog | null>(null);
  const [connections, setConnections] = useState<InstrumentConnection[]>([]);
  const [connection, setConnection] = useState<InstrumentConnection | null>(
    null,
  );
  const [sessions, setSessions] = useState<Session[]>([]);
  const [sessionId, setSessionId] = useState(initialSessionId ?? "");
  const [instrument, setInstrument] = useState<ConnectorInstrument>("flex");
  const [platform, setPlatform] = useState<ConnectorPlatform>("macos");
  const [name, setName] = useState("My Flex");
  const [pairing, setPairing] = useState<{
    code: string;
    expires_at: number;
  } | null>(null);
  const [preflight, setPreflight] = useState<ConnectorPreflight | null>(null);
  const [run, setRun] = useState<PhysicalRun | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [installConsent, setInstallConsent] = useState(false);
  const [motionConsent, setMotionConsent] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [now, setNow] = useState(Date.now());
  const alive = useRef(true);
  const lock = useRef(false);
  const refreshEpoch = useRef(0);
  const initialDesignApplied = useRef(false);
  const currentId = useRef(
    window.location.hash.match(/^#\/connect\/([a-f0-9-]+)$/)?.[1] ?? "",
  );
  const selection = useRef(sessionId);
  selection.current = sessionId;
  const session = sessions.find((item) => item.id === sessionId);
  const release = catalog?.releases.find(
    (item) => item.instrument === instrument,
  );
  const supportedPlatform =
    catalog?.companion.platforms.includes(platform) ?? false;
  const canDownload =
    catalog?.companion.status === "available" &&
    !!catalog.companion.download_url &&
    supportedPlatform &&
    installConsent;
  const expiresIn = pairing
    ? Math.max(0, Math.ceil((pairing.expires_at * 1000 - now) / 1000))
    : 0;
  const runMatchesReference =
    run?.run_id === pendingId && run?.connection_id === connection?.id;
  const resolvedUnknown = runMatchesReference && hasBoundResolution(run);
  const unresolvedRun =
    !!pendingId && !(runMatchesReference && (isFinal(run) || resolvedUnknown));
  const runCanStart =
    !!connection &&
    !connection.active_run_id &&
    preflight?.ready === true &&
    preflight.enabled === true &&
    !!preflight.native_run_id &&
    !!session &&
    preflight.connection_id === connection.id &&
    preflight.session_id === session.id &&
    preflight.session_version === session.version &&
    !unresolvedRun &&
    motionConsent &&
    !busy;

  const acceptConnection = useCallback((next: InstrumentConnection) => {
    if (!alive.current || next.id !== currentId.current) return;
    setConnection((old) =>
      old?.id === next.id && old.version > next.version ? old : next,
    );
    setConnections((old) => [
      next,
      ...old.filter((item) => item.id !== next.id),
    ]);
    setInstrument(next.instrument);
    setPlatform(next.platform);
    setName(next.display_name);
    if (next.status === "paired" || next.status === "revoked") setPairing(null);
  }, []);

  const load = useCallback(
    async (quiet = false) => {
      const epoch = ++refreshEpoch.current;
      const id = currentId.current;
      const selected = selection.current || savedWorkflowId(id);
      const [nextCatalog, list, saved] = await Promise.all([
        api<ConnectorCatalog>("/connectors/catalog"),
        api<{ connections: InstrumentConnection[] }>("/connections"),
        api<Session[]>("/sessions"),
      ]);
      if (
        !alive.current ||
        id !== currentId.current ||
        epoch !== refreshEpoch.current
      )
        return;
      setCatalog(nextCatalog);
      setConnections(list.connections);
      setSessions(
        saved.filter(
          (item) => item.experiment.course_id === "workflow-sandbox",
        ),
      );
      if (!id && selected && !initialDesignApplied.current) {
        const selectedDesign = saved.find((item) => item.id === selected);
        if (selectedDesign) {
          const model = selectedDesign.experiment.instrument ?? "flex";
          setInstrument(model);
          setName(model === "flex" ? "My Flex" : "My OT-2");
          initialDesignApplied.current = true;
        }
      }
      if (selected && !selection.current) {
        selection.current = selected;
        setSessionId(selected);
      }
      if (id) {
        const next = await api<InstrumentConnection>(`/connections/${id}`);
        if (
          !alive.current ||
          id !== currentId.current ||
          epoch !== refreshEpoch.current
        )
          return;
        acceptConnection(next);
        const requested = next.active_run_id ?? pendingRunId(id);
        if (requested) {
          setPendingId(requested);
          try {
            const nextRun = await api<PhysicalRun>(
              `/connections/${id}/runs/${requested}`,
            );
            if (
              alive.current &&
              currentId.current === id &&
              epoch === refreshEpoch.current
            ) {
              // A new operator resolution must be followed by a fresh readiness
              // response; a previously cached preflight cannot unlock a new run.
              if (hasBoundResolution(nextRun)) setPreflight(null);
              setRun((old) =>
                old?.run_id === nextRun.run_id && old.version > nextRun.version
                  ? old
                  : nextRun,
              );
              if (!selected) setSessionId(nextRun.session_id);
            }
          } catch (e) {
            if (!quiet || !(e instanceof ApiError && e.status === 404)) throw e;
          }
        }
        if (selected) {
          const nextPreflight = await api<ConnectorPreflight>(
            `/connections/${id}/preflight?session_id=${encodeURIComponent(selected)}`,
          );
          if (
            alive.current &&
            currentId.current === id &&
            epoch === refreshEpoch.current &&
            selection.current === selected
          )
            setPreflight(nextPreflight);
        }
      }
    },
    [acceptConnection],
  );

  useEffect(() => {
    alive.current = true;
    load()
      .catch((e) => {
        if (alive.current) {
          setPreflight(null);
          setError(messageOf(e));
        }
      })
      .finally(() => {
        if (alive.current) setLoading(false);
      });
    const poll = window.setInterval(() => {
      if (
        lock.current ||
        !currentId.current ||
        document.visibilityState !== "visible"
      )
        return;
      load(true).catch((e) => {
        if (alive.current) {
          setPreflight(null);
          setError(messageOf(e));
        }
      });
    }, 5000);
    return () => {
      alive.current = false;
      window.clearInterval(poll);
    };
  }, [load]);
  useEffect(() => {
    if (!pairing) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [pairing]);
  useEffect(() => {
    setPreflight(null);
    setMotionConsent(false);
    if (!currentId.current || !sessionId) return;
    const id = currentId.current;
    try {
      sessionStorage.setItem(workflowKey(id), sessionId);
    } catch {
      /* The saved connection can still be read without browser storage. */
    }
    api<ConnectorPreflight>(
      `/connections/${id}/preflight?session_id=${encodeURIComponent(sessionId)}`,
    )
      .then((value) => {
        if (
          alive.current &&
          currentId.current === id &&
          selection.current === sessionId
        )
          setPreflight(value);
      })
      .catch((e) => {
        if (alive.current) setError(messageOf(e));
      });
  }, [connection?.id, sessionId]);

  useEffect(() => {
    setMotionConsent(false);
  }, [
    session?.version,
    preflight?.plan_hash,
    preflight?.native_run_id,
    connection?.qualified,
    connection?.active_run_id,
    run?.resolution?.request.resolution_id,
  ]);

  const act = async (action: () => Promise<void>) => {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (e) {
      if (alive.current) setError(messageOf(e));
    } finally {
      lock.current = false;
      if (alive.current) setBusy(false);
    }
  };

  const downloadCompanion = () =>
    act(async () => {
      if (!canDownload) return;
      // Presigned links expire while the operator reads the setup page.
      const fresh = await api<ConnectorCatalog>(
        `/connectors/catalog?platform=${encodeURIComponent(platform)}`,
      );
      if (!alive.current) return;
      setCatalog(fresh);
      const companion = fresh.companion;
      if (
        companion.status !== "available" ||
        !companion.platforms.includes(platform) ||
        !companion.download_url
      )
        throw new Error(
          "The reviewed installer is no longer available. Refresh setup before continuing.",
        );
      const url = new URL(companion.download_url);
      if (url.protocol !== "https:" || url.username || url.password)
        throw new Error("The installer download address is invalid.");
      const link = document.createElement("a");
      link.href = url.href;
      link.download = "";
      link.rel = "noreferrer";
      document.body.appendChild(link);
      link.click();
      link.remove();
    });

  const create = () =>
    act(async () => {
      const id = crypto.randomUUID();
      currentId.current = id;
      window.history.replaceState({}, "", `/#/connect/${id}`);
      try {
        acceptConnection(
          await api<InstrumentConnection>(
            `/connections/${id}`,
            json(
              {
                expected_version: 0,
                instrument,
                display_name: name.trim(),
                platform,
              },
              "PUT",
            ),
          ),
        );
        setNotice(
          "Connection saved. Install the companion on the computer attached to this instrument, then pair it below.",
        );
      } catch (e) {
        // The request may have been accepted before the response was lost.
        try {
          acceptConnection(
            await api<InstrumentConnection>(`/connections/${id}`),
          );
          setNotice(
            "The connection was saved. Its current state has been recovered.",
          );
        } catch {
          setNotice(
            "The save outcome is unresolved. Refresh this connection before attempting another setup.",
          );
          throw e;
        }
      }
    });

  const pair = () =>
    act(async () => {
      if (!connection) return;
      setPairing(null);
      try {
        const result = await api<{
          connection: InstrumentConnection;
          code: string;
          expires_at: number;
        }>(
          `/connections/${connection.id}/pairing`,
          json({ expected_version: connection.version }),
        );
        acceptConnection(result.connection);
        if (alive.current) {
          setPairing({ code: result.code, expires_at: result.expires_at });
          setNow(Date.now());
        }
      } catch (e) {
        await load(true).catch(() => {});
        setNotice(
          "The saved pairing state was checked. A lost code cannot be recovered; explicitly create a new code when you are ready.",
        );
        throw e;
      }
    });

  const revoke = () =>
    act(async () => {
      if (!connection) return;
      try {
        acceptConnection(
          await api<InstrumentConnection>(
            `/connections/${connection.id}/revoke`,
            json({ expected_version: connection.version }),
          ),
        );
        setNotice(
          "This computer’s pairing has been revoked. Revocation is not a physical emergency stop.",
        );
      } catch (e) {
        await load(true).catch(() => {});
        throw e;
      }
    });

  const start = () =>
    act(async () => {
      if (!runCanStart || !connection || !preflight || !session) return;
      const id = crypto.randomUUID();
      // Persist the identity before sending. A lost response must never become a second physical command.
      sessionStorage.setItem(refKey(connection.id), id);
      if (sessionStorage.getItem(refKey(connection.id)) !== id)
        throw new Error(
          "This browser cannot save the run reference. Enable session storage before requesting physical motion.",
        );
      setPendingId(id);
      setRun(null);
      setMotionConsent(false);
      try {
        const next = await api<PhysicalRun>(
          `/connections/${connection.id}/runs`,
          json({
            run_id: id,
            expected_version: connection.version,
            session_id: session.id,
            session_version: preflight.session_version,
            native_run_id: preflight.native_run_id,
            acknowledge_physical_motion: true,
          }),
        );
        if (alive.current) setRun(next);
      } catch (e) {
        try {
          const next = await api<PhysicalRun>(
            `/connections/${connection.id}/runs/${id}`,
          );
          if (alive.current) setRun(next);
        } catch {
          setNotice(
            "The physical request has an unresolved outcome. Keep this run reference and refresh its status. No second run will be submitted automatically.",
          );
        }
        throw e;
      } finally {
        await load(true).catch(() => {});
      }
    });

  const stop = () =>
    act(async () => {
      if (!connection || !run) return;
      try {
        const next = await api<PhysicalRun>(
          `/connections/${connection.id}/runs/${run.run_id}/stop`,
          json({ expected_version: run.version }),
        );
        if (alive.current) setRun(next);
        setNotice(
          "A stop request was recorded. Wait for the instrument’s reported outcome; use the instrument’s physical emergency stop if needed.",
        );
      } catch (e) {
        await load(true).catch(() => {});
        throw e;
      }
    });

  const switchConnection = (id: string) => {
    if (busy) return;
    currentId.current = id;
    setConnection(null);
    setPairing(null);
    setRun(null);
    setPendingId(null);
    setPreflight(null);
    setMotionConsent(false);
    setError("");
    setNotice("");
    window.history.replaceState({}, "", id ? `/#/connect/${id}` : "/#/connect");
    if (id)
      void act(async () => {
        await load();
      });
  };

  return (
    <div className={s.page} data-testid="connector-setup">
      <button className={s.textButton} onClick={onBack}>
        <ArrowLeft size={15} /> Sim → Real
      </button>
      <header className={s.heading}>
        <div>
          <h1>Connect your instrument.</h1>
        </div>
        <button
          className={s.secondary}
          disabled={busy || loading}
          onClick={() =>
            act(async () => {
              await load();
              setNotice("Saved connection and workflow checks refreshed.");
            })
          }
        >
          <RefreshCw size={15} /> Refresh connection
        </button>
      </header>
      {error && (
        <div className={s.alert} role="alert">
          {error}
        </div>
      )}
      {notice && (
        <div className={s.notice} role="status">
          {notice}
        </div>
      )}
      {loading ? (
        <p role="status">
          Loading connector releases and your saved connections…
        </p>
      ) : (
        <div className={s.layout}>
          <nav className={s.rail} aria-label="Instrument connection steps">
            <ol>
              {[
                ["install", "Install", false],
                ["pair", "Pair", connection?.status === "paired"],
                ["checks", "Check", connection?.qualified === true],
                ["workflow", "Review & run", preflight?.ready === true],
              ].map(([id, title, done], index) => (
                <li key={String(id)}>
                  <span className={s.stepMarker} data-done={done}>
                    {done ? <Check size={12} /> : index + 1}
                  </span>
                  <a
                    href={`#connector-${id}`}
                    onClick={(event) => {
                      event.preventDefault();
                      document
                        .getElementById(`connector-${id}`)
                        ?.scrollIntoView({ block: "start" });
                    }}
                  >
                    {title}
                  </a>
                </li>
              ))}
            </ol>
          </nav>
          <div className={s.sections}>
            <section
              className={s.section}
              id="connector-install"
              aria-labelledby="connector-install-title"
            >
              <div className={s.sectionHeading}>
                <span className={s.sectionNumber}>01</span>
                <h2 id="connector-install-title">Install companion</h2>
              </div>
              {connections.length > 0 && (
                <label className={s.field}>
                  Saved connection
                  <select
                    value={connection?.id ?? currentId.current}
                    disabled={busy}
                    onChange={(e) => switchConnection(e.target.value)}
                  >
                    <option value="">Set up another instrument</option>
                    {connections.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.display_name} · {modelName(item.instrument)}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <fieldset
                className={s.models}
                disabled={busy || !!connection || !!currentId.current}
              >
                <legend>Instrument model</legend>
                {(["flex", "ot2"] as const).map((model) => (
                  <label key={model}>
                    <input
                      type="radio"
                      name="connector-instrument"
                      checked={instrument === model}
                      onChange={() => {
                        setInstrument(model);
                        setName(model === "flex" ? "My Flex" : "My OT-2");
                      }}
                    />
                    {modelName(model)}
                  </label>
                ))}
              </fieldset>
              <div className={s.fields}>
                <label className={s.field}>
                  Connection name
                  <input
                    value={name}
                    maxLength={80}
                    disabled={busy || !!connection || !!currentId.current}
                    onChange={(e) => setName(e.target.value)}
                  />
                </label>
                <label className={s.field}>
                  Computer operating system
                  <select
                    value={platform}
                    disabled={busy || !!connection || !!currentId.current}
                    onChange={(e) => {
                      setPlatform(e.target.value as ConnectorPlatform);
                      setInstallConsent(false);
                    }}
                  >
                    {Object.entries(platformName).map(([value, title]) => (
                      <option key={value} value={value}>
                        {title}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              {!connection && (
                <button
                  className={s.primary}
                  disabled={busy || !name.trim() || !!currentId.current}
                  onClick={create}
                >
                  <Laptop size={16} /> Save instrument connection
                </button>
              )}
              <details className={s.release}>
                <summary>
                  Connector release
                  <span className={s.status}>
                    {release?.status ?? "Unavailable"}
                  </span>
                </summary>
                <p>
                  {release?.reason ??
                    "No connector release information is available."}
                </p>
                {release && (
                  <p>
                    {release.version} ·{" "}
                    <code>{release.source_commit.slice(0, 12)}</code>
                  </p>
                )}
                <p>
                  {catalog?.companion.reason ??
                    "The companion installer is not available."}
                </p>
                {catalog?.companion.artifact_sha256 && (
                  <p>
                    Companion SHA-256:{" "}
                    <code>{catalog.companion.artifact_sha256}</code>
                  </p>
                )}
              </details>
              {catalog?.companion.status === "available" &&
                supportedPlatform && (
                  <label className={s.checkLabel}>
                    <input
                      type="checkbox"
                      checked={installConsent}
                      onChange={(e) => setInstallConsent(e.target.checked)}
                    />
                    I am using the computer connected to this instrument and
                    will review the installation prompt.
                  </label>
                )}
              <div className={s.actions}>
                {canDownload ? (
                  <button
                    className={s.primary}
                    onClick={downloadCompanion}
                    disabled={busy}
                  >
                    <Download size={16} /> Download companion for{" "}
                    {platformName[platform]}
                  </button>
                ) : (
                  <button className={s.primary} disabled>
                    <Download size={16} /> Download companion
                  </button>
                )}
                {catalog?.companion.status !== "available" ? (
                  <span className={s.status}>
                    Installer awaiting publication
                  </span>
                ) : !supportedPlatform ? (
                  <span className={s.status}>
                    No approved {platformName[platform]} package
                  </span>
                ) : null}
              </div>
              {catalog?.companion.status === "available" &&
                supportedPlatform && (
                  <p>
                    Open the package on this computer and keep the companion
                    running.
                  </p>
                )}
            </section>
            <section
              className={s.section}
              id="connector-pair"
              aria-labelledby="connector-pair-title"
            >
              <div className={s.sectionHeading}>
                <span className={s.sectionNumber}>02</span>
                <h2 id="connector-pair-title">Pair this computer</h2>
              </div>
              <p>
                Enter the code in your local companion. Pairing does not permit
                physical motion.
              </p>
              <span
                className={s.status}
                data-ready={connection?.status === "paired"}
              >
                <Link2 size={13} />
                {connection?.status ?? "Connection not saved"}
              </span>
              {pairing && connection?.status !== "paired" && (
                <div className={s.pairCode}>
                  {expiresIn > 0 ? (
                    <>
                      <output aria-label="Pairing code">{pairing.code}</output>
                      <button
                        className={s.secondary}
                        onClick={() =>
                          act(async () => {
                            await navigator.clipboard.writeText(pairing.code);
                            setNotice(
                              "Pairing code copied. Paste it only into your local Academy companion.",
                            );
                          })
                        }
                      >
                        <Copy size={15} /> Copy pairing code
                      </button>
                      <p>
                        Expires in {Math.floor(expiresIn / 60)}:
                        {String(expiresIn % 60).padStart(2, "0")}. Single use;
                        do not share.
                      </p>
                    </>
                  ) : (
                    <p role="status">
                      This pairing code has expired. Create a new code to
                      continue.
                    </p>
                  )}
                </div>
              )}
              <div className={s.actions}>
                <button
                  className={s.secondary}
                  disabled={
                    !connection || busy || connection.status === "paired"
                  }
                  onClick={pair}
                >
                  <Link2 size={15} />
                  {pairing || connection?.status === "pairing"
                    ? "Create a new pairing code"
                    : "Create pairing code"}
                </button>
                {connection &&
                  connection.status !== "unpaired" &&
                  connection.status !== "revoked" && (
                    <button
                      className={s.textButton}
                      disabled={busy}
                      onClick={revoke}
                    >
                      <Unplug size={15} /> Revoke this pairing
                    </button>
                  )}
              </div>
              {connection?.installation_id && (
                <details className={s.details}>
                  <summary>Pairing details</summary>
                  <dl className={s.binding}>
                    <dt>Installation</dt>
                    <dd>
                      <code>{connection.installation_id}</code>
                    </dd>
                  </dl>
                </details>
              )}
            </section>
            <section
              className={s.section}
              id="connector-checks"
              aria-labelledby="connector-checks-title"
            >
              <div className={s.sectionHeading}>
                <span className={s.sectionNumber}>03</span>
                <h2 id="connector-checks-title">Check the instrument</h2>
              </div>
              <ul className={s.checks}>
                <li data-passed={connection?.status === "paired"}>
                  {connection?.status === "paired" ? (
                    <Check size={16} />
                  ) : (
                    <Circle size={16} />
                  )}
                  <div>
                    <strong>Computer pairing</strong>
                    {connection?.status === "paired"
                      ? "Paired"
                      : "Waiting for pairing"}
                  </div>
                </li>
                <li data-passed={!!connection?.probe}>
                  {connection?.probe ? (
                    <Check size={16} />
                  ) : (
                    <Circle size={16} />
                  )}
                  <div>
                    <strong>Read-only instrument report</strong>
                    {connection?.probe ? "Report received" : "Awaiting report"}
                  </div>
                </li>
                <li data-passed={!!connection?.approved_release}>
                  {connection?.approved_release ? (
                    <Check size={16} />
                  ) : (
                    <Circle size={16} />
                  )}
                  <div>
                    <strong>Approved connector release</strong>
                    {connection?.approved_release
                      ? "Approved"
                      : "Approval required"}
                  </div>
                </li>
                <li data-passed={connection?.qualified === true}>
                  {connection?.qualified ? (
                    <ShieldCheck size={16} />
                  ) : (
                    <Circle size={16} />
                  )}
                  <div>
                    <strong>Physical qualification</strong>
                    {connection?.qualified ? "Qualified" : "Not qualified"}
                  </div>
                </li>
              </ul>
              {connection?.probe && (
                <>
                  <dl className={s.binding}>
                    <dt>Reported instrument</dt>
                    <dd>{modelName(connection.probe.instrument)}</dd>
                    <dt>Serial number</dt>
                    <dd>{connection.probe.serial}</dd>
                    <dt>Firmware</dt>
                    <dd>{connection.probe.firmware}</dd>
                    <dt>Connection report</dt>
                    <dd>
                      {connection.probe.reachable
                        ? "Reachable at the last check"
                        : "Unreachable at the last check"}
                    </dd>
                    <dt>Last checked</dt>
                    <dd>
                      {new Date(
                        connection.probe.observed_at * 1000,
                      ).toLocaleString()}
                    </dd>
                  </dl>
                  <details className={s.details}>
                    <summary>Read the instrument report</summary>
                    <pre>{JSON.stringify(connection.probe, null, 2)}</pre>
                  </details>
                </>
              )}
              <button
                className={s.secondary}
                disabled={!connection || busy}
                onClick={() =>
                  act(async () => {
                    await load();
                    setNotice(
                      "Read-only instrument reports refreshed. No motion was requested.",
                    );
                  })
                }
              >
                <RefreshCw size={15} /> Refresh read-only checks
              </button>
            </section>
            <section
              className={s.section}
              id="connector-workflow"
              aria-labelledby="connector-workflow-title"
            >
              <div className={s.sectionHeading}>
                <span className={s.sectionNumber}>04</span>
                <h2 id="connector-workflow-title">Review & run</h2>
              </div>
              <p>
                Requires a qualified instrument and native DT evidence for this
                saved workflow. Teaching results cannot unlock physical runs.
              </p>
              <label className={s.field}>
                Saved Studio workflow
                <select
                  value={sessionId}
                  disabled={busy || unresolvedRun}
                  onChange={(e) => setSessionId(e.target.value)}
                >
                  <option value="">Choose a saved workflow</option>
                  {sessions.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.experiment.title} ·{" "}
                      {modelName(item.experiment.instrument ?? "flex")}
                    </option>
                  ))}
                </select>
              </label>
              {!sessions.length && (
                <p>Save a workflow in Studio to continue.</p>
              )}
              {session && (
                <div className={s.workflow}>
                  <h3>{session.experiment.title}</h3>
                  <p>
                    {modelName(session.experiment.instrument ?? "flex")} ·{" "}
                    Version {session.version} ·{" "}
                    {Object.entries(session.experiment.layout)
                      .map(([slot, asset]) => `${slot}: ${asset}`)
                      .join(" · ")}
                  </p>
                  <ol>
                    {session.experiment.actions.map((action, index) => (
                      <li key={index}>
                        {action.kind === "pickup"
                          ? "Pick up a fresh tip"
                          : action.kind === "drop"
                            ? "Discard the tip"
                            : `${action.kind === "aspirate" ? "Aspirate" : "Dispense"} ${action.volume} µL ${action.kind === "aspirate" ? "from" : "into"} ${action.well}`}
                      </li>
                    ))}
                  </ol>
                  <button
                    className={s.textButton}
                    disabled={busy}
                    onClick={() => onOpen(session)}
                  >
                    Open design & native Matterix <ArrowRight size={15} />
                  </button>
                </div>
              )}
              {preflight ? (
                <>
                  <ul className={s.checks}>
                    {preflight.issues.map((issue) => (
                      <li key={issue.code}>
                        <Circle size={16} />
                        <div>
                          <strong>{issue.message}</strong>
                        </div>
                      </li>
                    ))}
                  </ul>
                  <span className={s.status} data-ready={preflight.ready}>
                    {preflight.ready
                      ? "Server preflight ready"
                      : "Physical run blocked"}
                  </span>
                  {preflight.native_run_id && (
                    <details className={s.details}>
                      <summary>Native DT evidence</summary>
                      <dl className={s.binding}>
                        <dt>Native DT evidence</dt>
                        <dd>
                          <code>{preflight.native_run_id}</code>
                        </dd>
                        <dt>Saved plan fingerprint</dt>
                        <dd>
                          <code>{preflight.plan_hash}</code>
                        </dd>
                      </dl>
                    </details>
                  )}
                </>
              ) : connection && session ? (
                <p role="status">
                  Checking the saved plan and native evidence…
                </p>
              ) : session && !connection ? (
                <p>Save an instrument connection to continue.</p>
              ) : null}
              <label className={s.checkLabel}>
                <input
                  type="checkbox"
                  checked={motionConsent}
                  disabled={!preflight?.ready || busy || unresolvedRun}
                  onChange={(e) => setMotionConsent(e.target.checked)}
                />
                I have reviewed this exact workflow, instrument identity and
                deck setup. The working area is clear, I am present at the
                instrument, and I authorize physical motion.
              </label>
              <div className={s.actions}>
                <button
                  className={s.primary}
                  disabled={!runCanStart}
                  onClick={start}
                >
                  <ArrowRight size={16} /> Request physical run
                </button>
              </div>
              <p>
                Native DT does not validate physical volume accuracy or
                chemistry.
              </p>
              {pendingId && (
                <div className={s.run} aria-label="Physical run status">
                  <h3>
                    {run
                      ? `Physical run: ${run.status}`
                      : "Physical run: outcome unresolved"}
                  </h3>
                  <dl className={s.binding}>
                    <dt>Physical run reference</dt>
                    <dd>
                      <code>{pendingId}</code>
                    </dd>
                    {run && (
                      <>
                        <dt>Updated</dt>
                        <dd>
                          {new Date(run.updated_at * 1000).toLocaleString()}
                        </dd>
                        <dt>Native evidence</dt>
                        <dd>
                          <code>{run.native_run_id}</code>
                        </dd>
                        <dt>Plan fingerprint</dt>
                        <dd>
                          <code>{run.plan_hash}</code>
                        </dd>
                      </>
                    )}
                  </dl>
                  {run?.reason && <p>{run.reason}</p>}
                  {run?.stop_requested && !resolvedUnknown && (
                    <p>
                      Stop requested. Physical stopping has not been assumed;
                      review the reported outcome.
                    </p>
                  )}
                  {resolvedUnknown ? (
                    <p role="status">
                      An operator verified that this instrument is stopped and
                      released. The original outcome remains unknown. This run
                      will not be replayed. Review the fresh checks and
                      authorize a new run separately.
                    </p>
                  ) : (
                    (!run || run.status === "unknown") && (
                      <p>
                        The outcome requires reconciliation. This page will
                        query the same run reference and will not repeat the
                        physical request.
                      </p>
                    )
                  )}
                  <div className={s.actions}>
                    <button
                      className={s.secondary}
                      disabled={busy}
                      onClick={() =>
                        act(async () => {
                          await load();
                        })
                      }
                    >
                      <RefreshCw size={15} /> Refresh physical run
                    </button>
                    {run && !isFinal(run) && !resolvedUnknown && (
                      <button
                        className={s.danger}
                        disabled={busy || run.stop_requested}
                        onClick={stop}
                      >
                        <Square size={13} /> Request instrument stop
                      </button>
                    )}
                  </div>
                  {run?.receipt && (
                    <details className={s.details}>
                      <summary>Read the physical execution receipt</summary>
                      <pre>{JSON.stringify(run.receipt, null, 2)}</pre>
                    </details>
                  )}
                  {resolvedUnknown && (
                    <details className={s.details}>
                      <summary>Read the operator reconciliation</summary>
                      <pre>{JSON.stringify(run?.resolution, null, 2)}</pre>
                    </details>
                  )}
                </div>
              )}
            </section>
          </div>
        </div>
      )}
    </div>
  );
}
