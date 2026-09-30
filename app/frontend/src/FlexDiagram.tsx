import type { EquipmentId } from "./learningContent";
import type { Session } from "./types";
import s from "./LearningLab.module.css";

export default function FlexDiagram({
  session,
  selected,
  onSelect,
}: {
  session: Session;
  selected: EquipmentId;
  onSelect: (id: EquipmentId) => void;
}) {
  const layout = session.experiment.layout;
  const tip = session.state.pipette;
  const target = session.state.wells.A1.volume;
  const highlight = (id: EquipmentId) =>
    selected === id ? "#be6033" : "#6f8574";
  return (
    <svg
      viewBox="0 0 720 530"
      className={s.diagram}
      role="img"
      aria-label="Flex 设备教学示意图，非实时三维画面。下方对象按钮提供相同选择功能。"
    >
      <defs>
        <linearGradient id="case" x2="0" y2="1">
          <stop stopColor="#f9faf7" />
          <stop offset="1" stopColor="#d8dfd7" />
        </linearGradient>
        <linearGradient id="bench" x2="0" y2="1">
          <stop stopColor="#f4f6f0" />
          <stop offset="1" stopColor="#e2e8dd" />
        </linearGradient>
        <pattern id="grid" width="24" height="24" patternUnits="userSpaceOnUse">
          <path
            d="M 24 0 L 0 0 0 24"
            fill="none"
            stroke="#d8dfd3"
            strokeWidth=".6"
          />
        </pattern>
      </defs>
      <rect width="720" height="530" fill="#edf0e7" />
      <rect width="720" height="530" fill="url(#grid)" />
      <ellipse
        cx="355"
        cy="486"
        rx="272"
        ry="20"
        fill="#314d3a"
        opacity=".08"
      />
      <path
        d="M 89 106 L 124 64 H 596 L 632 106 V 465 H 89 Z"
        fill="url(#case)"
        stroke="#aebbad"
        strokeWidth="2"
      />
      <rect x="117" y="116" width="486" height="327" rx="8" fill="#d0dbce" />
      <rect
        x="128"
        y="126"
        width="464"
        height="304"
        rx="4"
        fill="url(#bench)"
      />
      <text
        x="123"
        y="93"
        fontSize="18"
        fontWeight="700"
        fill="#365445"
        letterSpacing="3"
      >
        FLEX
      </text>
      <text x="493" y="91" fontSize="11" fill="#566b58">
        TEACHING VIEW
      </text>
      <text x="363" y="148" textAnchor="middle" fontSize="10" fill="#61715e">
        后方 · BACK
      </text>
      {[..."ABCD"].flatMap((r, row) =>
        [1, 2, 3].map((col) => {
          const slot = `${r}${col}`;
          const x = 154 + (col - 1) * 136;
          const y = 159 + row * 61;
          const item = Object.entries(layout).find(
            ([, v]) => v === slot,
          )?.[0] as EquipmentId | undefined;
          return (
            <g
              key={slot}
              onClick={() => item && onSelect(item)}
              className={item ? s.clickable : undefined}
            >
              <rect
                x={x}
                y={y}
                width="122"
                height="53"
                rx="5"
                fill={item === selected ? "#fff5de" : "#f9faf5"}
                stroke={item === selected ? "#be6033" : "#c1cdbb"}
                strokeWidth={item === selected ? 2 : 1}
              />
              <text
                x={x + 6}
                y={y + 12}
                fontSize="9"
                fontWeight="600"
                fill="#697962"
              >
                {slot}
              </text>
              {item === "tips" && (
                <g>
                  <rect
                    x={x + 24}
                    y={y + 9}
                    width="78"
                    height="34"
                    rx="3"
                    fill="#d3df9f"
                    stroke="#748853"
                  />
                  {Array.from({ length: 24 }, (_, i) => (
                    <circle
                      key={i}
                      cx={x + 32 + (i % 8) * 9}
                      cy={y + 16 + Math.floor(i / 8) * 10}
                      r="2.5"
                      fill="#5d734c"
                    />
                  ))}
                </g>
              )}
              {item === "stock" && (
                <g>
                  <ellipse
                    cx={x + 63}
                    cy={y + 41}
                    rx="17"
                    ry="4"
                    fill="#bbcabc"
                  />
                  <rect
                    x={x + 50}
                    y={y + 14}
                    width="26"
                    height="24"
                    rx="5"
                    fill="#edf8ee"
                    stroke="#709578"
                  />
                  <rect
                    x={x + 52}
                    y={y + 24}
                    width="22"
                    height="12"
                    rx="3"
                    fill="#71aa85"
                  />
                  <ellipse
                    cx={x + 63}
                    cy={y + 15}
                    rx="13"
                    ry="4"
                    fill="#cbdbd0"
                    stroke="#709578"
                  />
                </g>
              )}
              {item === "plate" && (
                <g>
                  <rect
                    x={x + 24}
                    y={y + 8}
                    width="79"
                    height="37"
                    rx="3"
                    fill="#e9edf2"
                    stroke="#839694"
                  />
                  {Array.from({ length: 24 }, (_, i) => (
                    <circle
                      key={i}
                      cx={x + 32 + (i % 8) * 9}
                      cy={y + 15 + Math.floor(i / 8) * 10}
                      r="3"
                      fill={i === 0 && target > 0 ? "#5e9c7b" : "#c8d8d9"}
                      stroke={i === 0 ? "#be6033" : "#95abaa"}
                      strokeWidth={i === 0 ? 1.5 : 0.5}
                    />
                  ))}
                  <text x={x + 27} y={y + 54} fontSize="8" fill="#a24925">
                    A1 孔
                  </text>
                </g>
              )}
              {item === "waste" && (
                <g>
                  <path
                    d={`M${x + 35} ${y + 12}h60l-9 33h-43z`}
                    fill="#b4c1b0"
                    stroke="#738570"
                  />
                  <ellipse
                    cx={x + 65}
                    cy={y + 12}
                    rx="30"
                    ry="8"
                    fill="#61785e"
                  />
                  <text
                    x={x + 64}
                    y={y + 34}
                    textAnchor="middle"
                    fill="#f7f8ec"
                    fontSize="9"
                  >
                    固定 D3
                  </text>
                </g>
              )}
            </g>
          );
        }),
      )}
      <g onClick={() => onSelect("pipette")} className={s.clickable}>
        <rect x="133" y="118" width="454" height="12" rx="3" fill="#a6b6a3" />
        <rect
          x="400"
          y="104"
          width="45"
          height="45"
          rx="5"
          fill="#e3e9de"
          stroke={highlight("pipette")}
          strokeWidth="2"
        />
        <path d="M410 149h25v23h-25z" fill="#748b73" />
        <path d="M416 172h13l-4 23h-5z" fill="#b3c8b2" stroke="#6d876e" />
        {tip.tip && (
          <path
            d="M419 193h7l-2 24h-3z"
            fill={tip.volume > 0 ? "#459878" : "#f8f4cf"}
            stroke="#6d876e"
          />
        )}
        <path d="M445 124h46l19-14" stroke={highlight("pipette")} fill="none" />
        <text x="511" y="108" fill={highlight("pipette")} fontSize="12">
          移液器
        </text>
      </g>
      <path d="M 90 442 H 632 V 466 H 90 Z" fill="#b6c6b1" />
      <text x="360" y="458" textAnchor="middle" fontSize="10" fill="#3f593f">
        前方 · FRONT / 学生面对设备的方向
      </text>
      <rect x="526" y="449" width="75" height="10" rx="3" fill="#74906b" />
      <text x="29" y="30" fontSize="10" fill="#74806a" letterSpacing="2">
        EXPLORE THE INSTRUMENT
      </text>
      <text x="29" y="511" fontSize="10" fill="#677660">
        示意图用于设备定位 · 不展示真实运动、碰撞或液面
      </text>
    </svg>
  );
}
