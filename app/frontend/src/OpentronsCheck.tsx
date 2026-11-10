import { CheckCircle2, Download, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { api, apiBlob } from "./api";
import s from "./OpentronsCheck.module.css";

type Finding = { step: number | null; message: string };
type Result = {
  robot: string;
  pipette: string;
  tips: string;
  plate: string;
  stock: string;
  api_level: string;
  stops: Finding[];
  unnoticed: Finding[];
};

function Findings({ items }: { items: Finding[] }) {
  return (
    <ul>
      {items.map((item, index) => (
        <li key={index}>
          <TriangleAlert size={16} aria-hidden="true" />
          <span>
            {item.step ? `Step ${item.step} · ` : ""}
            {item.message}
          </span>
        </li>
      ))}
    </ul>
  );
}

export default function OpentronsCheck({
  sessionId,
  dirty,
  onError,
}: {
  sessionId: string;
  dirty: boolean;
  onError: (message: string) => void;
}) {
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async (work: () => Promise<void>) => {
    setBusy(true);
    try {
      await work();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const shown = dirty ? null : result;
  return (
    <section className={s.section} aria-labelledby="opentrons-check">
      <div className={s.heading}>
        <h2 id="opentrons-check">On a real Opentrons</h2>
        <span>PRE-CHECK · NOT A ROBOT RUN</span>
      </div>
      <div className={s.actions}>
        <button
          className={s.secondary}
          disabled={busy || dirty}
          onClick={() =>
            run(async () =>
              setResult(
                await api<Result>(`/sessions/${sessionId}/opentrons-check`),
              ),
            )
          }
        >
          Check my workflow
        </button>
        {shown && shown.stops.length === 0 && (
          <button
            className={s.secondary}
            disabled={busy}
            onClick={() =>
              run(async () => {
                const url = URL.createObjectURL(
                  await apiBlob(`/sessions/${sessionId}/opentrons-protocol`),
                );
                Object.assign(document.createElement("a"), {
                  href: url,
                  download: "academy_protocol.py",
                }).click();
                URL.revokeObjectURL(url);
              })
            }
          >
            <Download size={15} /> Download protocol (.py)
          </button>
        )}
        {dirty && <p className={s.reason}>Save your workflow first.</p>}
      </div>
      {shown && (
        <div className={s.result} role="status">
          {shown.stops.length > 0 ? (
            <div>
              <h3>
                Opentrons would stop at {shown.stops.length}{" "}
                {shown.stops.length === 1 ? "step" : "steps"}
              </h3>
              <Findings items={shown.stops} />
            </div>
          ) : (
            <h3 className={s.ok}>
              <CheckCircle2 size={18} aria-hidden="true" /> Opentrons would run
              every step
            </h3>
          )}
          {shown.unnoticed.length > 0 && (
            <div>
              <h3>Opentrons runs these without a warning</h3>
              <Findings items={shown.unnoticed} />
            </div>
          )}
          <details>
            <summary>What was checked</summary>
            <p>
              {shown.robot} · {shown.pipette} · {shown.tips} · plate{" "}
              {shown.plate} · stock {shown.stock} · API {shown.api_level}
            </p>
            <p>
              The rules follow what the Opentrons simulator did with the same
              mistakes. Import the downloaded file into the Opentrons App to get
              its own analysis before any run.
            </p>
          </details>
        </div>
      )}
    </section>
  );
}
