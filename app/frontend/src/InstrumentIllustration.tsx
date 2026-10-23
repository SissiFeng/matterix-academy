import { useId } from "react";
import type {
  StoryInstrument,
  StoryWorkflow,
} from "./instrumentStoriesContent";
import { STUDIO_LAYOUTS } from "./studioContent";
import s from "./InstrumentStories.module.css";

const clamp = (value: number) => Math.max(0, Math.min(1, value));
const ease = (value: number) => {
  const bounded = clamp(value);
  return bounded * bounded * (3 - 2 * bounded);
};
const between = (from: number, to: number, fraction: number) =>
  from + (to - from) * ease(fraction);

/** Seekable illustration: every visual is derived from time, without a timer. */
export default function InstrumentIllustration({
  instrument,
  time = 0,
  workflow = "transfer",
  overview = false,
  className,
}: {
  instrument: StoryInstrument;
  time?: number;
  workflow?: StoryWorkflow;
  overview?: boolean;
  className?: string;
}) {
  const id = useId().replace(/:/g, "");
  const flex = instrument === "flex";
  const currentTime = overview ? 0 : Math.max(0, Math.min(36, time));
  const layout = STUDIO_LAYOUTS[instrument];
  const slotPosition = (slot: string) => {
    const row = flex
      ? "ABCD".indexOf(slot[0])
      : 3 - Math.floor((Number(slot) - 1) / 3);
    const column = flex ? Number(slot[1]) - 1 : (Number(slot) - 1) % 3;
    return { x: 166 + column * 130, y: 248 + row * 49 };
  };
  const stock = slotPosition(layout.stock);
  const plate = slotPosition(layout.plate);
  const tips = slotPosition(layout.tips);
  const waste = slotPosition(layout.waste);
  const targetPositions = [31, 56, 81].map((offset) => plate.x + offset);
  const tipX = tips.x + 59;
  const tipY = tips.y + 13;
  const sourceX = stock.x + 58;
  const sourceY = stock.y + 17;
  const sampleY = plate.y + 17;
  const trashX = waste.x + 56;
  const trashY = waste.y + 19;
  let pipetteX = 354;
  let pipetteY = 251;
  if (currentTime >= 9 && currentTime < 14) {
    pipetteX = between(354, tipX, (currentTime - 9) / 2);
    pipetteY = between(251, tipY, (currentTime - 9) / 3);
  } else if (currentTime >= 14 && currentTime < 20) {
    pipetteX = between(tipX, sourceX, (currentTime - 14) / 2);
    pipetteY = between(tipY, sourceY, (currentTime - 14) / 2);
  } else if (currentTime >= 20 && currentTime < 29) {
    const localTime = currentTime - 20;
    if (workflow === "transfer") {
      pipetteX = between(sourceX, targetPositions[0], localTime / 3);
    } else if (workflow === "distribute") {
      const phase = Math.min(2, Math.floor(localTime / 3));
      pipetteX = between(
        phase === 0 ? sourceX : targetPositions[phase - 1],
        targetPositions[phase],
        (localTime - phase * 3) / 1.4,
      );
    }
    pipetteY =
      between(sourceY, sampleY, localTime / 3) -
      Math.sin(clamp(localTime / 3) * Math.PI) * 38;
    if (workflow === "dilution") {
      // The starter uses a fresh tip for each of its three transfers.
      const points = [
        { at: 20, x: sourceX, y: sourceY },
        { at: 21, x: targetPositions[0], y: sampleY },
        { at: 22.2, x: trashX, y: trashY },
        { at: 22.8, x: tipX + 9, y: tipY },
        { at: 23.4, x: targetPositions[0], y: sampleY },
        { at: 24.6, x: targetPositions[1], y: sampleY },
        { at: 25.5, x: trashX, y: trashY },
        { at: 26.2, x: tipX + 18, y: tipY },
        { at: 27, x: targetPositions[1], y: sampleY },
        { at: 28.2, x: targetPositions[2], y: sampleY },
        { at: 29, x: targetPositions[2], y: sampleY },
      ];
      const next = points.findIndex((point) => point.at > currentTime);
      const start = points[next - 1];
      const end = points[next];
      const fraction = (currentTime - start.at) / (end.at - start.at);
      pipetteX = between(start.x, end.x, fraction);
      pipetteY =
        between(start.y, end.y, fraction) -
        Math.sin(clamp(fraction) * Math.PI) * 24;
    }
  } else if (currentTime >= 29 && currentTime < 33) {
    pipetteX = between(
      workflow === "transfer" ? targetPositions[0] : targetPositions[2],
      trashX,
      (currentTime - 29) / 2,
    );
    pipetteY = between(sampleY, trashY, (currentTime - 29) / 2);
  } else if (currentTime >= 33) {
    pipetteX = between(trashX, 354, (currentTime - 33) / 2);
    pipetteY = between(trashY, 251, (currentTime - 33) / 2);
  }
  const changingTip =
    workflow === "dilution" &&
    ((currentTime >= 22.2 && currentTime < 22.8) ||
      (currentTime >= 25.5 && currentTime < 26.2));
  const hasTip = currentTime >= 11 && currentTime < 31.5 && !changingTip;
  const aspirated = clamp((currentTime - 16) / 3);
  const dispensed = clamp(
    (currentTime - 22) / (workflow === "transfer" ? 2 : 6),
  );
  let liquidInTip = hasTip ? aspirated * (1 - dispensed) : 0;
  if (workflow === "dilution" && currentTime >= 20) {
    liquidInTip =
      currentTime < 21
        ? 1 - clamp((currentTime - 20.5) / 0.5)
        : currentTime >= 23.4 && currentTime < 24.6
          ? 1 - clamp((currentTime - 24.1) / 0.5)
          : currentTime >= 27 && currentTime < 28.2
            ? 1 - clamp((currentTime - 27.7) / 0.5)
            : 0;
  }
  const liquidColor =
    workflow === "dilution" && currentTime >= 23.4
      ? currentTime >= 27
        ? "#b6a2c0"
        : "#b46c91"
      : "#c46845";
  const movingLiquid = currentTime >= 16 && currentTime < 29;
  const deckFocus = currentTime >= 5 && currentTime < 10;
  const tipsFocus = currentTime >= 10 && currentTime < 14;
  const sourceFocus = currentTime >= 14 && currentTime < 20;
  const sampleFocus = currentTime >= 20 && currentTime < 29;
  const trashFocus = currentTime >= 29 && currentTime < 33;
  const slots = Array.from({ length: 12 }, (_, index) => {
    const row = Math.floor(index / 3);
    const column = index % 3;
    return {
      label: flex
        ? `${"ABCD"[row]}${column + 1}`
        : String((3 - row) * 3 + column + 1),
      x: 166 + column * 130,
      y: 248 + row * 49,
    };
  });

  return (
    <svg
      viewBox="0 0 760 535"
      className={`${s.illustration} ${className ?? ""}`}
      role="img"
      aria-label={`${flex ? "Opentrons Flex with a modular frame and side touchscreen" : "Opentrons OT-2 with an enclosed gantry"}. Illustrative teaching view. ${flex ? "Deck slots A1 through D3." : "Deck slots 1 through 11 and trash at position 12."}`}
      data-testid={overview ? undefined : "instrument-illustration"}
      data-instrument={instrument}
      data-story-time={Math.floor(currentTime)}
    >
      <defs>
        <linearGradient id={`${id}-frame`} x1="0" y1="0" x2="0.8" y2="1">
          <stop stopColor="#fffefa" />
          <stop offset="1" stopColor="#cbd4ce" />
        </linearGradient>
        <linearGradient id={`${id}-deck`} x1="0" y1="0" x2="0" y2="1">
          <stop stopColor="#dce6dc" />
          <stop offset="1" stopColor="#f3f5ed" />
        </linearGradient>
        <linearGradient id={`${id}-glass`} x1="0" y1="0" x2="1" y2="1">
          <stop stopColor="#bad1ce" stopOpacity=".36" />
          <stop offset=".6" stopColor="#f5faf7" stopOpacity=".08" />
          <stop offset="1" stopColor="#87aaa3" stopOpacity=".25" />
        </linearGradient>
        <pattern
          id={`${id}-grid`}
          width="30"
          height="30"
          patternUnits="userSpaceOnUse"
        >
          <path
            d="M30 0H0V30"
            fill="none"
            stroke="currentColor"
            strokeWidth=".6"
            opacity=".1"
          />
        </pattern>
        <marker
          id={`${id}-arrow`}
          viewBox="0 0 10 10"
          refX="8"
          refY="5"
          markerWidth="5"
          markerHeight="5"
          orient="auto-start-reverse"
        >
          <path d="m0 0 10 5-10 5Z" fill="#c46b4b" />
        </marker>
      </defs>

      <rect
        x="21"
        y="19"
        width="718"
        height="498"
        rx="28"
        fill={`url(#${id}-grid)`}
      />
      <ellipse
        cx="376"
        cy="489"
        rx={flex ? 277 : 256}
        ry="20"
        fill="#274234"
        opacity=".09"
      />
      {flex ? (
        <g>
          <path
            d="m107 96 38-40h438l40 40v356H107Z"
            fill={`url(#${id}-frame)`}
            stroke="#899d91"
            strokeWidth="2"
          />
          <rect x="128" y="94" width="473" height="352" rx="9" fill="#273b34" />
          <rect
            x="146"
            y="113"
            width="437"
            height="323"
            rx="6"
            fill="#d1dfd5"
          />
          <path d="M146 114h437v95H146Z" fill={`url(#${id}-glass)`} />
          <rect
            x="103"
            y="436"
            width="523"
            height="42"
            rx="7"
            fill={`url(#${id}-frame)`}
            stroke="#899d91"
            strokeWidth="2"
          />
          <text
            x="140"
            y="464"
            fontSize="17"
            letterSpacing="4"
            fontWeight="800"
            fill="#304d3e"
          >
            FLEX
          </text>
          <circle cx="582" cy="457" r="5" fill="#97c96a" />
          <path d="M622 168h19v70h-19" fill="#7d9488" />
          <rect
            x="629"
            y="130"
            width="89"
            height="129"
            rx="9"
            fill="#2c4139"
            stroke="#93a79b"
            strokeWidth="2"
          />
          <rect x="636" y="139" width="75" height="103" rx="4" fill="#dfecda" />
          <circle cx="673" cy="166" r="12" fill="#477856" />
          <path
            d="m667 166 4 4 8-9"
            fill="none"
            stroke="#edf4e4"
            strokeWidth="3"
          />
          <rect x="648" y="190" width="50" height="4" rx="2" fill="#9eaf99" />
          <rect x="648" y="201" width="34" height="4" rx="2" fill="#b6c5ad" />
          <text
            x="673"
            y="227"
            textAnchor="middle"
            fontSize="9"
            fontWeight="700"
            fill="#365445"
          >
            TEACHING
          </text>
          {!overview && (
            <text x="673" y="283" textAnchor="middle" className={s.annotation}>
              Touchscreen
            </text>
          )}
          <rect x="124" y="472" width="38" height="12" rx="3" fill="#42574c" />
          <rect x="568" y="472" width="38" height="12" rx="3" fill="#42574c" />
        </g>
      ) : (
        <g>
          <path
            d="m128 104 36-47h423l41 47v355H128Z"
            fill={`url(#${id}-frame)`}
            stroke="#8b9d93"
            strokeWidth="2"
          />
          <path
            d="M146 110h462v333H146Z"
            fill="#d6e1da"
            stroke="#54766c"
            strokeWidth="3"
          />
          <path d="m146 110 23 30v289l-23 14Z" fill="#adc8c4" opacity=".65" />
          <path d="m608 110-31 30v289l31 14Z" fill="#92b5ae" opacity=".6" />
          <path d="M169 140h408v289H169Z" fill={`url(#${id}-glass)`} />
          <rect
            x="126"
            y="73"
            width="505"
            height="44"
            rx="7"
            fill={`url(#${id}-frame)`}
            stroke="#8b9d93"
            strokeWidth="2"
          />
          <text
            x="158"
            y="101"
            fontSize="19"
            fontWeight="800"
            letterSpacing="3"
            fill="#304d3e"
          >
            OT-2
          </text>
          <text
            x="489"
            y="99"
            fontSize="10"
            fontWeight="600"
            letterSpacing="1"
            fill="#55776c"
          >
            OPENTRONS
          </text>
          <rect
            x="119"
            y="437"
            width="519"
            height="39"
            rx="5"
            fill={`url(#${id}-frame)`}
            stroke="#8b9d93"
            strokeWidth="2"
          />
          <rect x="136" y="468" width="36" height="15" rx="3" fill="#42574c" />
          <rect x="582" y="468" width="36" height="15" rx="3" fill="#42574c" />
          <path d="M137 144v261m481-261v261" stroke="#778d83" strokeWidth="5" />
          <rect x="611" y="224" width="12" height="62" rx="6" fill="#3b6255" />
          {!overview && (
            <g>
              <path d="M119 194H79" stroke="#8b9f92" strokeWidth="1.5" />
              <text x="72" y="188" textAnchor="end" className={s.annotation}>
                Enclosure
              </text>
            </g>
          )}
        </g>
      )}

      <rect
        x="160"
        y="241"
        width="388"
        height="195"
        rx="7"
        fill={`url(#${id}-deck)`}
        stroke="#869e8f"
        strokeWidth="2"
      />
      {slots.map(({ label, x, y }) => (
        <g key={label}>
          <rect
            x={x}
            y={y}
            width="121"
            height="43"
            rx="4"
            fill="#f8faf2"
            stroke={deckFocus ? "#be6746" : "#b5c5b7"}
            strokeWidth={deckFocus ? 2 : 1}
          />
          <text
            x={x + 7}
            y={y + 13}
            fontSize="12"
            fontWeight="700"
            fill="#52715e"
          >
            {label}
          </text>
        </g>
      ))}

      {/* Stock, sample wells and tips use deliberately different silhouettes. */}
      <g
        transform={`translate(${stock.x - 166}, ${stock.y - 346})`}
        data-labware="stock"
        data-slot={layout.stock}
      >
        <rect
          x="193"
          y="351"
          width="69"
          height="32"
          rx="7"
          fill={sourceFocus ? "#ffedce" : "#ebefe7"}
          stroke={sourceFocus ? "#bc633e" : "#8faaa1"}
          strokeWidth={sourceFocus ? 3 : 1.5}
        />
        <ellipse
          cx="224"
          cy="371"
          rx="17"
          ry="7"
          fill="#a34e39"
          opacity=".25"
        />
        <path
          d="M209 351v18c0 10 30 10 30 0v-18"
          fill="#efd3a5"
          stroke="#ac754d"
          strokeWidth="1.3"
        />
        <path
          d={`M211 ${357 + aspirated * 6}V368Q224 375 237 368V${357 + aspirated * 6}Z`}
          fill="#ce7151"
        />
        <ellipse
          cx="224"
          cy="351"
          rx="15"
          ry="6"
          fill="#e2a37a"
          stroke="#ac754d"
          strokeWidth="1.3"
        />
        <ellipse cx="224" cy="351" rx="10" ry="3.5" fill="#bc593e" />
      </g>
      <g
        transform={`translate(${plate.x - 296}, ${plate.y - 346})`}
        data-labware="plate"
        data-slot={layout.plate}
      >
        <rect
          x="314"
          y="348"
          width="78"
          height="36"
          rx="5"
          fill={sampleFocus ? "#fcf0d9" : "#e1e8df"}
          stroke={sampleFocus ? "#bc633e" : "#859c8b"}
          strokeWidth={sampleFocus ? 3 : 1.5}
        />
        {[327, 352, 377].map((x, index) => {
          const reached =
            workflow === "transfer"
              ? index === 0 && currentTime >= 23
              : workflow === "dilution"
                ? currentTime >= [21, 24.6, 28.2][index]
                : currentTime >= 21.5 + index * 3;
          const colors =
            workflow === "dilution"
              ? ["#b46c91", "#b6a2c0", "#ccc0d4"]
              : ["#ce7151", "#ce7151", "#ce7151"];
          return (
            <g key={x}>
              <path
                d={`M${x - 8} 356v15c0 7 16 7 16 0v-15`}
                fill={workflow === "dilution" ? "#c9e0e4" : "#f4f7ef"}
                stroke="#77978e"
                strokeWidth="1.3"
              />
              {reached && (
                <path
                  d={`M${x - 6} 362v8c0 5 12 5 12 0v-8`}
                  fill={colors[index]}
                />
              )}
              <ellipse
                cx={x}
                cy="356"
                rx="8"
                ry="4"
                fill={
                  reached
                    ? colors[index]
                    : workflow === "dilution"
                      ? "#c0dce3"
                      : "#e5eee6"
                }
                stroke="#77978e"
                strokeWidth="1.3"
              />
              <text
                x={x}
                y="382"
                textAnchor="middle"
                fontSize="6.5"
                fontWeight="700"
                fill="#365445"
              >{`A${index + 1}`}</text>
            </g>
          );
        })}
      </g>
      <g
        transform={`translate(${tips.x - 166}, ${tips.y - 395})`}
        data-labware="tips"
        data-slot={layout.tips}
      >
        <rect
          x="188"
          y="400"
          width="81"
          height="28"
          rx="4"
          fill="#c5d9aa"
          stroke={tipsFocus ? "#bc633e" : "#748b62"}
          strokeWidth={tipsFocus ? 3 : 1.5}
        />
        {Array.from({ length: 16 }, (_, index) => (
          <circle
            key={index}
            cx={198 + (index % 8) * 9}
            cy={408 + Math.floor(index / 8) * 11}
            r="2.8"
            fill={
              (index === 3 && currentTime >= 11) ||
              (workflow === "dilution" &&
                ((index === 4 && currentTime >= 22.8) ||
                  (index === 5 && currentTime >= 26.2)))
                ? "#b1c59a"
                : "#496d4b"
            }
          />
        ))}
      </g>
      <g
        transform={`translate(${waste.x - 426}, ${waste.y - 248})`}
        data-labware="waste"
        data-slot={layout.waste}
      >
        <path
          d="M455 264h52l-5 23h-42Z"
          fill="#7a9185"
          stroke={trashFocus ? "#bd6545" : "#536d5b"}
          strokeWidth={trashFocus ? 3 : 1.5}
        />
        <ellipse
          cx="481"
          cy="264"
          rx="27"
          ry="7"
          fill="#3e574a"
          stroke={trashFocus ? "#bd6545" : "#536d5b"}
          strokeWidth={trashFocus ? 3 : 1.5}
        />
        {currentTime >= 31.5 && <path d="m475 259 4 15 4-15" fill="#dce9cb" />}
        {workflow === "dilution" && currentTime >= 22.2 && (
          <path d="m484 258 4 15 4-15" fill="#dce9cb" />
        )}
        {workflow === "dilution" && currentTime >= 25.5 && (
          <path d="m465 258 4 15 4-15" fill="#dce9cb" />
        )}
        <text
          x="481"
          y="282"
          textAnchor="middle"
          fontSize="8"
          fontWeight="700"
          fill="#f6f8ef"
        >
          TRASH
        </text>
      </g>

      {!overview && currentTime >= 5 && (
        <g>
          <path
            d={`M${tips.x + 23} ${tipY + 3}H132l-22-16H57`}
            fill="none"
            stroke="#7d9584"
            strokeWidth="1.5"
          />
          <text x="57" y={tipY - 23} className={s.annotation}>
            Tip rack
          </text>
          <path
            d={`M${stock.x + 27} ${sourceY + 2}H126l-22 23H57`}
            fill="none"
            stroke="#ab7a56"
            strokeWidth="1.5"
          />
          <text x="57" y={sourceY + 43} className={s.annotation}>
            Stock
          </text>
          <path
            d={`M${plate.x + 97} ${sampleY + 8}H554l28-37h136`}
            fill="none"
            stroke="#8b8aa1"
            strokeWidth="1.5"
          />
          <text
            x="718"
            y={sampleY - 40}
            textAnchor="end"
            className={s.annotation}
          >
            Sample wells
          </text>
        </g>
      )}

      {movingLiquid && (
        <path
          d={
            workflow === "transfer"
              ? `M${sourceX + 11} ${sourceY - 20}Q${(sourceX + targetPositions[0]) / 2} ${Math.min(sourceY, sampleY) - 59} ${targetPositions[0] - 10} ${sampleY - 20}`
              : `M${sourceX + 11} ${sourceY - 20}Q${(sourceX + targetPositions[0]) / 2} ${Math.min(sourceY, sampleY) - 54} ${targetPositions[0] - 10} ${sampleY - 20}M${targetPositions[0] + 8} ${sampleY - 23}q5-12 12 1M${targetPositions[1] + 8} ${sampleY - 23}q5-12 12 1`
          }
          fill="none"
          stroke="#c46b4b"
          strokeWidth="2.5"
          strokeDasharray="4 5"
          markerEnd={`url(#${id}-arrow)`}
          opacity=".85"
        />
      )}

      {/* An XY carriage and pipette. Geometry is illustrative, not a motion plan. */}
      <g>
        <rect
          x="154"
          y="159"
          width="422"
          height="19"
          rx="3"
          fill={flex ? "#8ca594" : "#5e9187"}
          stroke="#526d5c"
        />
        <rect x="166" y="165" width="398" height="5" rx="2" fill="#c3d5c4" />
        <path
          d={`M${pipetteX} 169v${Math.max(0, pipetteY - 262)}`}
          stroke="#526b5c"
          strokeWidth="7"
        />
        <rect
          x={pipetteX - 19}
          y="151"
          width="38"
          height="33"
          rx="4"
          fill="#dae4d6"
          stroke="#6b8675"
          strokeWidth="2"
        />
        <g transform={`translate(${pipetteX}, ${pipetteY - 99})`}>
          <rect
            x="-16"
            y="0"
            width="32"
            height="65"
            rx="7"
            fill="#f2f5e9"
            stroke="#607e69"
            strokeWidth="2"
          />
          <rect
            x="-10"
            y="9"
            width="20"
            height="29"
            rx="3"
            fill={flex ? "#385f4c" : "#4d8078"}
          />
          <path
            d="M-8 65h16v11l-5 5h-6l-5-5Z"
            fill="#a8bdaa"
            stroke="#607e69"
            strokeWidth="1.5"
          />
          <path d="M-3 81h6v7h-6Z" fill="#7c9580" />
          {hasTip && (
            <g>
              <path
                d="M-6 86h12L2 102h-4Z"
                fill="#e8f0d6"
                stroke="#6d8d65"
                strokeWidth="1.2"
              />
              {liquidInTip > 0 && (
                <path
                  d={`M${-2 - liquidInTip * 2} ${101 - liquidInTip * 12}h${4 + liquidInTip * 4}L1 101h-2Z`}
                  fill={liquidColor}
                />
              )}
            </g>
          )}
        </g>
        {!overview && currentTime < 10 && (
          <g>
            <path
              d="M374 216h78l24-15h57"
              fill="none"
              stroke="#6c8e78"
              strokeWidth="1.5"
            />
            <text
              x="537"
              y="195"
              textAnchor="end"
              className={s.machineAnnotation}
            >
              Pipette
            </text>
          </g>
        )}
      </g>

      {!overview && (
        <g>
          <path d="M348 498h28m-19-4 5 4-5 4" fill="none" stroke="#849a88" />
          <text x="388" y="502" className={s.annotation}>
            Front of the deck
          </text>
          <text x="54" y="48" className={s.figureLabel}>
            {flex ? "01 / FLEX" : "02 / OT-2"}
          </text>
        </g>
      )}
    </svg>
  );
}
