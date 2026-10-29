import { useEffect, useRef, useState } from "react";
import { api, json } from "./api";
import type { Session } from "./types";
import s from "./ConnectorSetup.module.css";

type MockRun = {
  run_id: string;
  version: number;
  session_id: string;
  session_version: number;
  transport: "in-process-mock";
  evidence: "synthetic";
  simulation: Session;
};
const key = (sessionId: string) => `academy-mock-connector:${sessionId}`;

export default function MockConnector({ sessions }: { sessions: Session[] }) {
  const workflows = sessions.filter(
    (item) => item.experiment.course_id === "workflow-sandbox",
  );
  const [selected, setSelected] = useState("");
  const [run, setRun] = useState<MockRun | null>(null);
  const [reference, setReference] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const lock = useRef(false);
  const session = workflows.find((item) => item.id === selected);
  useEffect(() => {
    let active = true;
    setRun(null);
    setError("");
    const id = sessionStorage.getItem(key(selected));
    setReference(id);
    if (id)
      api<MockRun>(`/connector-mock/runs/${id}`)
        .then((value) => {
          if (active) setRun(value);
        })
        .catch((reason) => {
          if (active) setError(reason.message);
        });
    return () => {
      active = false;
    };
  }, [selected]);

  async function act(command: "create" | "step" | "run" | "reset" | "refresh") {
    if (lock.current || !session) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      if (command === "create") {
        const id = reference ?? crypto.randomUUID();
        sessionStorage.setItem(key(selected), id);
        setReference(id);
        setRun(
          await api<MockRun>(
            "/connector-mock/runs",
            json({
              run_id: id,
              session_id: session.id,
              expected_version: session.version,
            }),
          ),
        );
      } else if (command === "refresh" && reference) {
        setRun(await api<MockRun>(`/connector-mock/runs/${reference}`));
      } else if (run) {
        setRun(
          await api<MockRun>(
            `/connector-mock/runs/${run.run_id}/commands`,
            json({
              expected_version: run.version,
              command,
            }),
          ),
        );
      }
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Offline connector request failed. Refresh the run to reconcile its state.",
      );
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  const runnable = run && ["draft", "running"].includes(run.simulation.status);
  return (
    <section className={s.section} aria-labelledby="offline-connector-title">
      <h2 id="offline-connector-title">Try an offline connector</h2>
      <p>
        Run a saved workflow without an instrument, installer or GPU. This mock
        SiLA2 adapter produces synthetic state only. The browser uses an
        in-process mock; a separate local SiLA2 server is available for client
        development.
      </p>
      <label className={s.field}>
        Offline workflow
        <select
          value={selected}
          disabled={busy}
          onChange={(event) => setSelected(event.target.value)}
        >
          <option value="">Pick a workflow to run offline</option>
          {workflows.map((item) => (
            <option key={item.id} value={item.id}>
              {item.experiment.title} ·{" "}
              {item.experiment.instrument === "ot2" ? "OT-2" : "Flex"}
            </option>
          ))}
        </select>
      </label>
      {!workflows.length && (
        <p>Save a workflow in Studio to try the offline connector.</p>
      )}
      <div className={s.actions}>
        <button
          className={s.secondary}
          disabled={!session || busy || !!run}
          onClick={() => act("create")}
        >
          Prepare offline run
        </button>
        <button
          className={s.primary}
          disabled={!runnable || busy}
          onClick={() => act("step")}
        >
          Next mock step
        </button>
        <button
          className={s.primary}
          disabled={!runnable || busy}
          onClick={() => act("run")}
        >
          Run all mock steps
        </button>
        <button
          className={s.secondary}
          disabled={!run || busy}
          onClick={() => act("reset")}
        >
          Reset mock run
        </button>
        <button
          className={s.secondary}
          disabled={!reference || busy}
          onClick={() => act("refresh")}
        >
          Refresh offline run
        </button>
      </div>
      {error && <p role="alert">{error}</p>}
      {run && (
        <div className={s.workflow} aria-label="Offline connector state">
          <h3>
            Synthetic · {run.simulation.status} · Step {run.simulation.cursor}/
            {run.simulation.experiment.actions.length}
          </h3>
          <p>
            Saved revision {run.session_version} · {run.transport} · No physical
            execution
          </p>
          <p>
            Tip: {run.simulation.state.pipette.tip ? "attached" : "detached"} ·
            Pipette: {run.simulation.state.pipette.volume} µL
          </p>
          <ul>
            {Object.entries(run.simulation.state.wells).map(([name, well]) => (
              <li key={name}>
                {name}: {well.volume} µL
              </li>
            ))}
          </ul>
          {run.simulation.events.at(-1) && (
            <p role="status">{run.simulation.events.at(-1)?.message}</p>
          )}
          <a
            className={s.textButton}
            href={`data:application/json;charset=utf-8,${encodeURIComponent(JSON.stringify(run, null, 2))}`}
            download={`mock-connector-${run.run_id}.json`}
          >
            Download synthetic run JSON
          </a>
        </div>
      )}
    </section>
  );
}
