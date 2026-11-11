import { useEffect, useRef, useState } from "react";
import { api, ApiError, json } from "./api";
import type { GpuStatus } from "./simulationTypes";
import s from "./NativeStudioRun.module.css";

type Capacity = {
  configured: boolean;
  active: boolean;
  request: { request_id: string; expires_at: number } | null;
  gpu: GpuStatus | null;
};

/** Capacity can be requested before a saved plan qualifies for execution. */
export default function GpuRequestPanel({
  session,
}: {
  session: { id: string; version: number };
}) {
  const [capacity, setCapacity] = useState<Capacity | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const sending = useRef(false);
  const mutation = useRef(0);
  const pending = useRef<{
    request_id: string;
    expected_version: number;
  } | null>(null);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    let timer: number | undefined;
    const controller = new AbortController();
    // Only a host that is changing power state, or a request whose response was
    // lost, is worth reading every few seconds.
    let changing = true;
    const read = async () => {
      if (document.hidden) {
        timer = window.setTimeout(read, 3000);
        return;
      }
      const epoch = mutation.current;
      try {
        const next = await api<Capacity>(
          `/sessions/${session.id}/gpu-request`,
          { signal: controller.signal },
        );
        if (!controller.signal.aborted && epoch === mutation.current) {
          setCapacity(next);
          changing = ["starting", "preparing", "stopping"].includes(
            next.gpu?.state ?? "",
          );
          if (next.active) setError("");
          if (
            next.request &&
            next.request.request_id === pending.current?.request_id
          ) {
            pending.current = null;
            setError("");
          }
        }
      } catch {
        if (!controller.signal.aborted && epoch === mutation.current)
          setError(
            "GPU availability could not be checked. Check connection to recover your request.",
          );
      } finally {
        if (!controller.signal.aborted)
          timer = window.setTimeout(
            read,
            changing || pending.current ? 3000 : 10000,
          );
      }
    };
    void read();
    return () => {
      alive.current = false;
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [session.id, refresh]);

  const request = async () => {
    if (sending.current) return;
    sending.current = true;
    mutation.current += 1;
    setBusy(true);
    setError("");
    pending.current ??= {
      request_id: crypto.randomUUID(),
      expected_version: session.version,
    };
    try {
      const next = await api<Capacity>(
        `/sessions/${session.id}/gpu-request`,
        json(pending.current),
      );
      if (alive.current) {
        setCapacity(next);
        pending.current = null;
      }
    } catch (cause) {
      if (alive.current) {
        if (
          cause instanceof ApiError &&
          [409, 422, 503].includes(cause.status)
        ) {
          pending.current = null;
          setError(cause.message);
        } else {
          setError(
            "The GPU request could not be confirmed. Check connection before trying again.",
          );
        }
      }
    } finally {
      sending.current = false;
      if (alive.current) {
        setBusy(false);
        // Read again now: the host may have started changing, or the response was lost.
        setRefresh((n) => n + 1);
      }
    }
  };

  return (
    <div className={s.preflight} aria-label="GPU allocation">
      <strong>Digital twin GPU</strong>
      <p role="status" aria-label="Digital twin availability">
        {capacity?.gpu?.message ??
          (capacity && !capacity.configured
            ? "GPU allocation is not configured in this deployment."
            : "Checking GPU availability…")}
      </p>
      {capacity?.gpu?.detail && (
        <p className={s.gpuDetail}>Worker reports: {capacity.gpu.detail}</p>
      )}
      {capacity?.gpu?.state === "capacity_wait" && capacity.gpu.attempts ? (
        <p className={s.gpuDetail}>
          Capacity attempts so far: {capacity.gpu.attempts}
        </p>
      ) : null}
      <div className={s.actions}>
        <button
          disabled={busy || capacity?.active}
          onClick={() => void request()}
        >
          {busy
            ? "Requesting GPU…"
            : capacity?.active
              ? "GPU requested"
              : "Request GPU"}
        </button>
        <button
          disabled={busy}
          onClick={() => {
            setError("");
            setRefresh((value) => value + 1);
          }}
        >
          Check GPU connection
        </button>
      </div>
      {capacity?.active && (
        <p>
          Request accepted. Capacity is shared; workflows run in order. GPU
          startup may take several minutes.
        </p>
      )}
      <p>
        Requesting a GPU does not run your workflow. Native execution still
        requires a qualified worker and a supported saved design. Idle GPUs shut
        down after one hour.
      </p>
      {error && (
        <p role="alert" className={s.warning}>
          {error}
        </p>
      )}
    </div>
  );
}
