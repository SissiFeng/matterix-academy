import type { CSSProperties } from "react";
import { ArrowRight } from "lucide-react";
import Pictogram from "./Pictogram";
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
                        <Pictogram name={stop.target} />
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
