import { ArrowRight, Check } from "lucide-react";
import s from "./InstrumentModules.module.css";
import {
  capabilityNames,
  capabilityOrder,
  modules,
  robotParts,
  unitOperations,
  type Media,
} from "./instrumentModulesContent";
import type { Instrument, Starter } from "./studioContent";

function MediaFigure({ media }: { media: Media }) {
  return (
    <figure className={s.media}>
      {media.kind === "video" ? (
        <video
          src={media.src}
          controls
          preload="metadata"
          aria-label={media.alt}
        />
      ) : (
        <img src={media.src} alt={media.alt} loading="lazy" />
      )}
      <figcaption>{media.credit}</figcaption>
    </figure>
  );
}

export default function InstrumentModules({
  onDesign,
  busy,
}: {
  onDesign: (instrument: Instrument, starter: Starter) => void;
  busy: boolean;
}) {
  return (
    <div className={s.modules}>
      <section aria-labelledby="robot-parts-title">
        <h2 id="robot-parts-title">What the robot is made of</h2>
        <ul className={s.parts}>
          {robotParts.map((part) => (
            <li key={part.name}>
              {part.media && <MediaFigure media={part.media} />}
              <h3>{part.name}</h3>
              <p>{part.job}</p>
              {part.robots.length === 1 && (
                <span className={s.robotTag}>{part.robots[0]} only</span>
              )}
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="module-table-title">
        <h2 id="module-table-title">Modules add jobs to the deck</h2>
        <div
          className={s.tableScroll}
          role="region"
          aria-labelledby="module-table-title"
          tabIndex={0}
        >
          <table className={s.table}>
            <thead>
              <tr>
                <th scope="col">Module</th>
                {capabilityOrder.map((item) => (
                  <th scope="col" key={item}>
                    {capabilityNames[item]}
                  </th>
                ))}
                <th scope="col">Works with</th>
              </tr>
            </thead>
            <tbody>
              {modules.map((module) => (
                <tr key={module.name}>
                  <th scope="row">
                    <strong>{module.name}</strong>
                    <small>{module.note}</small>
                  </th>
                  {capabilityOrder.map((item) => (
                    <td key={item}>
                      {module.does.includes(item) ? (
                        <>
                          <Check size={16} aria-hidden="true" />
                          <span className={s.srOnly}>Yes</span>
                        </>
                      ) : (
                        <>
                          <span className={s.no} aria-hidden="true">
                            –
                          </span>
                          <span className={s.srOnly}>No</span>
                        </>
                      )}
                    </td>
                  ))}
                  <td className={s.robots}>{module.robots.join(" · ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section aria-labelledby="unit-operations-title">
        <h2 id="unit-operations-title">
          Parts and modules become unit operations
        </h2>
        <ul className={s.operations}>
          {unitOperations.map((operation) => (
            <li key={operation.name}>
              {operation.media && <MediaFigure media={operation.media} />}
              <h3>{operation.name}</h3>
              <p>{operation.what}</p>
              <ul className={s.uses} aria-label={`${operation.name} uses`}>
                {operation.uses.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
              {operation.practice ? (
                <button
                  className={s.practise}
                  disabled={busy}
                  aria-label={`Practise ${operation.name.toLowerCase()}`}
                  onClick={() =>
                    onDesign(
                      operation.practice!.instrument,
                      operation.practice!.starter,
                    )
                  }
                >
                  Practise <ArrowRight size={15} />
                </button>
              ) : (
                <span className={s.unavailable}>
                  Not in the teaching model yet
                </span>
              )}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
