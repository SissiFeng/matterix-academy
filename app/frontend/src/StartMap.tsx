import type { CSSProperties, ReactNode } from "react";
import { ArrowRight } from "lucide-react";
import w from "./Workcell.module.css";
import s from "./StartMap.module.css";

type Stop = { target: string; title: string; detail: string };
const routes: { id: string; title: string; who: string; stops: Stop[] }[] = [
  {
    id: "learn",
    title: "Learning route",
    who: "New here",
    stops: [
      {
        target: "instruments",
        title: "Meet the robot",
        detail: "Parts, modules and what each one does",
      },
      {
        target: "learn",
        title: "Learn by level",
        detail: "From a first transfer to full workflows",
      },
      {
        target: "sim",
        title: "Simulate",
        detail: "Run a whole experiment before the real robot",
      },
      {
        target: "marketplace",
        title: "Adapt a workflow",
        detail: "Borrow a published method",
      },
      {
        target: "groups",
        title: "Compare with classmates",
        detail: "Share and agree on one workflow",
      },
    ],
  },
  {
    id: "use",
    title: "Using route",
    who: "Own instrument",
    stops: [
      {
        target: "onboard",
        title: "Add a device",
        detail: "Record the instrument from your lab",
      },
      {
        target: "twin",
        title: "Practise on its twin",
        detail: "A software copy that behaves like it",
      },
      {
        target: "plan",
        title: "Plan the bench",
        detail: "Find a layout that runs the workflow",
      },
      {
        target: "readiness",
        title: "Check readiness",
        detail: "What stands before a real run",
      },
      {
        target: "runs",
        title: "Review runs",
        detail: "Replay what happened, step by step",
      },
    ],
  },
];

/** One small drawing per stop, on a 48 × 48 grid. */
const art: Record<string, ReactNode> = {
  instruments: (
    <>
      <rect
        x="8"
        y="10"
        width="32"
        height="28"
        rx="3"
        fill="var(--surface-1)"
      />
      <path d="M8 17h32M24 24v5" />
      <rect x="20" y="14" width="8" height="10" rx="1.5" fill="var(--brand)" />
      <rect x="12" y="31" width="7" height="4" rx="1" fill="var(--accent)" />
      <rect x="21" y="31" width="7" height="4" rx="1" fill="var(--info)" />
      <rect x="30" y="31" width="7" height="4" rx="1" fill="var(--warn)" />
    </>
  ),
  learn: (
    <>
      <path d="M8 39h32V18h-8v7h-8v7h-8v7z" fill="var(--surface-1)" />
      <path d="M36 18V7" />
      <path d="M36 7l-9 3.5 9 3.5z" fill="var(--accent)" />
    </>
  ),
  sim: (
    <>
      <rect
        x="7"
        y="10"
        width="34"
        height="23"
        rx="3"
        fill="var(--surface-1)"
      />
      <path d="M21 16l9 5.5-9 5.5z" fill="var(--accent)" />
      <path d="M17 39h14M24 33v6" />
    </>
  ),
  marketplace: (
    <>
      <rect x="7" y="8" width="13" height="9" rx="2" fill="var(--info)" />
      <rect x="7" y="30" width="13" height="9" rx="2" fill="var(--brand)" />
      <path d="M13.5 17v13M20 34.5h6" />
      <path d="M29 31l10-10 3 3-10 10-4 1z" fill="var(--warn)" />
    </>
  ),
  groups: (
    <>
      <path
        d="M10 9h16a4 4 0 014 4v8a4 4 0 01-4 4h-8l-6 5v-5h-2a4 4 0 01-4-4v-8a4 4 0 014-4z"
        fill="var(--surface-1)"
      />
      <path
        d="M24 21h14a4 4 0 014 4v6a4 4 0 01-4 4h-1v4l-5-4h-8a4 4 0 01-4-4v-6a4 4 0 014-4z"
        fill="var(--accent)"
      />
      <path d="M12 15h12M12 19h7" />
    </>
  ),
  onboard: (
    <>
      <path d="M22 12l14 7v15l-14 7-14-7V19z" fill="var(--surface-1)" />
      <path d="M8 19l14 7 14-7M22 26v15" />
      <circle cx="37" cy="12" r="7" fill="var(--accent)" />
      <path d="M37 8.5v7M33.5 12h7" stroke="var(--on-brand)" />
    </>
  ),
  twin: (
    <>
      <rect x="5" y="13" width="15" height="22" rx="2.5" fill="var(--brand)" />
      <rect
        x="28"
        y="13"
        width="15"
        height="22"
        rx="2.5"
        fill="var(--surface-1)"
        strokeDasharray="3 2.5"
      />
      <path d="M21.5 20h5M26.5 28h-5" />
    </>
  ),
  plan: (
    <>
      <rect
        x="6"
        y="10"
        width="36"
        height="28"
        rx="3"
        fill="var(--surface-1)"
      />
      <rect x="10" y="14" width="11" height="8" rx="1.5" fill="var(--info)" />
      <rect x="29" y="26" width="9" height="8" rx="1.5" fill="var(--warn)" />
      <path d="M15 31l10-8 6 3" />
      <circle cx="15" cy="31" r="3.2" fill="var(--brand)" />
    </>
  ),
  readiness: (
    <>
      <rect
        x="11"
        y="9"
        width="26"
        height="31"
        rx="3"
        fill="var(--surface-1)"
      />
      <rect x="18" y="6" width="12" height="6" rx="2" fill="var(--brand)" />
      <path d="M27 21h6M27 31h6" />
      <path
        d="M16 20.5l2.5 2.5 4.5-5M16 30.5l2.5 2.5 4.5-5"
        stroke="var(--ok)"
        strokeWidth="2.2"
      />
    </>
  ),
  runs: (
    <>
      <circle cx="24" cy="24" r="14" fill="var(--surface-1)" stroke="none" />
      <path d="M11.5 20A13 13 0 1 1 13 31" />
      <path d="M10 12v8h8" />
      <path d="M21 18.5l8.5 5.5-8.5 5.5z" fill="var(--accent)" />
    </>
  ),
};

/** A road through evenly spaced stops: a wave across, or a wiggle down a phone. */
const road = (count: number, upright: boolean) => {
  const points = Array.from({ length: count }, (_, index) =>
    upright
      ? { x: index % 2 ? 100 : 54, y: 62 + index * 104 }
      : { x: ((index + 0.5) / count) * 1000, y: index % 2 ? 160 : 92 },
  );
  const last = points[count - 1];
  const end = upright ? { x: last.x, y: last.y + 82 } : { x: 978, y: last.y };
  let d = upright ? `M54 6V${points[0].y}` : `M22 92H${points[0].x}`;
  points.slice(1).forEach((to, index) => {
    const from = points[index];
    d += upright
      ? `C${from.x} ${(from.y + to.y) / 2} ${to.x} ${(from.y + to.y) / 2} ${to.x} ${to.y}`
      : `C${(from.x + to.x) / 2} ${from.y} ${(from.x + to.x) / 2} ${to.y} ${to.x} ${to.y}`;
  });
  d += upright ? `V${end.y}` : `H${end.x}`;
  return {
    d,
    points,
    end,
    width: upright ? 360 : 1000,
    height: upright ? end.y + 14 : 290,
  };
};

export default function StartMap({
  canPlan,
  onNavigate,
  onFirstLesson,
}: {
  canPlan: boolean;
  onNavigate: (target: string) => void;
  onFirstLesson: () => void;
}) {
  return (
    <section className={s.roadmap} aria-labelledby="roadmap-title">
      <h2 id="roadmap-title">Where to start</h2>
      {routes.map((route) => {
        const stops = route.stops.filter(
          (stop) => stop.target !== "plan" || canPlan,
        );
        const across = road(stops.length, false);
        const down = road(stops.length, true);
        return (
          <section
            key={route.id}
            className={s.route}
            data-route={route.id}
            aria-labelledby={`route-${route.id}`}
          >
            <header>
              <h3 id={`route-${route.id}`}>{route.title}</h3>
              <span className={s.who}>{route.who}</span>
              {route.id === "learn" && (
                <button className={w.primary} onClick={onFirstLesson}>
                  Start learning Flex <ArrowRight size={16} />
                </button>
              )}
            </header>
            <div
              className={s.map}
              style={
                {
                  "--across": `${across.width} / ${across.height}`,
                  "--down": `${down.width} / ${down.height}`,
                } as CSSProperties
              }
            >
              {[across, down].map((lane) => (
                <svg
                  key={lane.width}
                  className={lane === across ? s.across : s.down}
                  viewBox={`0 0 ${lane.width} ${lane.height}`}
                  aria-hidden="true"
                >
                  <path className={s.kerb} d={lane.d} />
                  <path className={s.tarmac} d={lane.d} />
                  <path className={s.dashes} d={lane.d} />
                  <g transform={`translate(${lane.end.x} ${lane.end.y})`}>
                    <path className={s.pole} d="M0 0V-34" />
                    <path className={s.flag} d="M0 -34l20 6.5L0 -21z" />
                  </g>
                  <g className={s.traveller}>
                    <circle r="9" />
                    <path d="M-3.5 0l2.5 2.5 4.5-5" />
                    <animateMotion
                      dur="18s"
                      repeatCount="indefinite"
                      path={lane.d}
                    />
                  </g>
                </svg>
              ))}
              <ol>
                {stops.map((stop, index) => (
                  <li
                    key={stop.target}
                    style={
                      {
                        "--ax": `${across.points[index].x / 10}%`,
                        "--ay": `${(across.points[index].y / across.height) * 100}%`,
                        "--dx": `${(down.points[index].x / down.width) * 100}%`,
                        "--dy": `${(down.points[index].y / down.height) * 100}%`,
                      } as CSSProperties
                    }
                  >
                    <button
                      title={stop.detail}
                      onClick={() => onNavigate(stop.target)}
                    >
                      <span className={s.badge} aria-hidden="true">
                        <svg viewBox="0 0 48 48">{art[stop.target]}</svg>
                        <span className={s.number}>{index + 1}</span>
                      </span>
                      <strong>{stop.title}</strong>
                    </button>
                  </li>
                ))}
              </ol>
            </div>
          </section>
        );
      })}
    </section>
  );
}
