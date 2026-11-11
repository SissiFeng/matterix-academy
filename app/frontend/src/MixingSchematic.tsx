import type { MixingPlan, TwinFrame } from "./simulationTypes";
import s from "./SimulationLab.module.css";

/** A drawn deck for teaching-twin runs. Never a live or native view. */
export default function MixingSchematic({
  name,
  plan,
  frame,
  active,
}: {
  name: string;
  plan: MixingPlan | undefined;
  frame: TwinFrame | undefined;
  /** The step being replayed, if any. */
  active: number | null;
}) {
  const step = active == null ? undefined : plan?.actions[active];
  const source = step?.kind === "transfer" ? step.source_index : null;
  const mixture = frame?.mixture_components_ul.reduce((a, b) => a + b, 0) ?? 0;
  const lidParked = frame?.lid_parked ?? false;
  const used = frame?.tips_used.length ?? 0;
  const vialX = (index: number) => 96 + index * 62;
  return (
    <section className={s.viewport} aria-label="Teaching twin schematic">
      <div className={s.viewportBar}>
        <span>
          <i className={active == null ? s.waitDot : s.liveDot} />
          {name}
        </span>
        <span>SYNTHETIC · NOT A LIVE VIEW</span>
      </div>
      <svg
        className={s.schematic}
        viewBox="0 0 720 450"
        role="img"
        aria-label={`Schematic of the mixing deck: ${mixture} µL in well A1, ${used} of 4 tips used, lid ${lidParked ? "parked" : "over the vials"}`}
      >
        <rect x="40" y="60" width="640" height="340" rx="10" />
        <text x="64" y="96">
          C1 · SOURCE VIALS
        </text>
        {Array.from({ length: 8 }, (_, index) => {
          const level = (frame?.source_volumes_ul[index] ?? 1500) / 1500;
          return (
            <g key={index} data-active={source === index || undefined}>
              <rect
                className={s.vessel}
                x={vialX(index)}
                y="120"
                width="40"
                height="96"
                rx="6"
              />
              <rect
                className={s.liquid}
                x={vialX(index) + 3}
                y={123 + 90 * (1 - level)}
                width="34"
                height={90 * level}
                rx="4"
              />
              <text x={vialX(index) + 20} y="238" textAnchor="middle">
                {index + 1}
              </text>
            </g>
          );
        })}
        <rect
          className={s.lid}
          data-shown={!lidParked || undefined}
          x="88"
          y="104"
          width="490"
          height="14"
          rx="4"
        />
        <rect
          className={s.lid}
          data-shown={lidParked || undefined}
          x="544"
          y="308"
          width="110"
          height="14"
          rx="4"
        />
        <text x="64" y="296">
          TIPS
        </text>
        {Array.from({ length: 4 }, (_, index) => (
          <circle
            key={index}
            className={s.tip}
            data-used={index < used || undefined}
            cx={76 + index * 34}
            cy="328"
            r="11"
          />
        ))}
        <text x="300" y="296">
          WELL A1
        </text>
        <rect
          className={s.vessel}
          x="300"
          y="308"
          width="150"
          height="56"
          rx="6"
        />
        <rect
          className={s.liquid}
          x="303"
          y="311"
          width={(144 * Math.min(mixture, 40)) / 40}
          height="50"
          rx="4"
        />
        <text x="375" y="342" textAnchor="middle" className={s.amount}>
          {mixture} µL
        </text>
        <text x="544" y="296">
          D4 · LID PARK
        </text>
        {source != null && (
          <path
            className={s.route}
            d={`M ${vialX(source) + 20} 246 C ${vialX(source) + 20} 280, 375 270, 375 302`}
          />
        )}
      </svg>
      <footer>
        <span>Bookkeeping only · no physics, video or hardware</span>
        <span>Volumes, tips and lid follow the saved twin</span>
      </footer>
    </section>
  );
}
