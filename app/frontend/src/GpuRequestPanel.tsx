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
    const read = async () => {
      const epoch = mutation.current;
      try {
        const next = await api<Capacity>(
          `/sessions/${session.id}/gpu-request`,
          { signal: controller.signal },
        );
        if (!controller.signal.aborted && epoch === mutation.current) {
          setCapacity(next);
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
        if (!controller.signal.aborted) timer = window.setTimeout(read, 3000);
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
      if (alive.current) setBusy(false);
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
