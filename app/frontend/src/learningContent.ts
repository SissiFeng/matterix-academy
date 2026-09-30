import type { Experiment, LearningProgress } from "./types";

export const PHASES = [
  { id: "orient", title: "认识设备", detail: "把手动经验映射到 Flex" },
  { id: "prepare", title: "准备台面", detail: "检查耗材、位置和液体" },
  { id: "predict", title: "预测变化", detail: "先想一想液体会去哪里" },
  { id: "run", title: "逐步运行", detail: "观察每一个动作的结果" },
  { id: "reflect", title: "复盘与再试", detail: "用新体积检验你的理解" },
] as const;

export const EQUIPMENT = {
  pipette: {
    name: "移液器",
    english: "Pipette",
    purpose: "负责吸取和排出液体，相当于你手中的移液枪。移动由机器人完成。",
    notice:
      "先确认量程与吸头兼容性。这里是上限 300 µL 的教学模型，不代表所有 Flex 移液器。",
    manual: "手动：调节移液枪体积",
    robot: "自动化：在动作中明确体积与目标孔",
  },
  tips: {
    name: "吸头架",
    english: "Tip rack",
    purpose: "存放一次性吸头。移液器先取头，才能接触和转移液体。",
    notice: "本课每次转移用一个新吸头；其他实验的换头策略要按污染风险设计。",
    manual: "手动：装上一个新吸头",
    robot: "自动化：先安排 Pick up tip 动作",
  },
  stock: {
    name: "源容器",
    english: "Source",
    purpose: "盛放准备转移的教学液体，是这次实验的起点。",
    notice:
      "机器需要你提供初始液量。当前显示为课程模型推算，不是液位传感器测量。",
    manual: "手动：找到试剂并判断余量",
    robot: "自动化：明确源容器、孔位和初始体积",
  },
  plate: {
    name: "目标孔板",
    english: "Well plate",
    purpose:
      "接收液体。每个孔有自己的地址，例如 A1、A2；孔板本身也占一个台面槽位。",
    notice: "D2 槽位 → 目标孔板 → A1 孔。槽位和孔位是两个不同层级。",
    manual: "手动：把枪头移到目标孔",
    robot: "自动化：使用确定的耗材和孔位地址",
  },
  waste: {
    name: "废弃槽",
    english: "Waste chute",
    purpose: "接收本次用过的吸头。Flex 的废弃槽安装在台面 D3 位置。",
    notice:
      "Waste chute 固定在 D3，不能随意拖动；它与可移动的 trash bin 不同。",
    manual: "手动：将用过的吸头打入废物容器",
    robot: "自动化：在转移完成后安排 Discard tip",
  },
};
export type EquipmentId = keyof typeof EQUIPMENT;
export const EMPTY_LEARNING: LearningProgress = {
  phase: "orient",
  visited: [],
  checks: [],
  location_answer: "",
  prediction: null,
  reflection: "",
};
export const PREPARATION = [
  {
    id: "instrument",
    title: "移液器与吸头",
    detail:
      "确认本课使用教学移液器，目标体积在 1–300 µL 练习范围内，吸头可用。",
  },
  {
    id: "labware",
    title: "耗材与位置",
    detail:
      "源容器、孔板和吸头架各占一个槽位；废弃槽在 D3。图中的 A1 孔属于目标孔板。",
  },
  {
    id: "liquids",
    title: "起始液量",
    detail: "源容器起始 1,000 µL，目标孔为空。这里练习直接转移，不需要稀释液。",
  },
  {
    id: "simulation",
    title: "本次练习的范围",
    detail:
      "这是课程模型推算，不包含碰撞、液面高度或真实移液精度；没有连接实体机器。",
  },
];

export function firstTransfer(volume = 100): Experiment {
  return {
    title: `第一次转移 · ${volume} µL`,
    course_id: "flex-first-transfer",
    transfer_volume: volume,
    layout: { stock: "D1", plate: "D2", tips: "B1", waste: "D3" },
    source_volume: 1000,
    diluent_volume: 0,
    actions: [
      { kind: "pickup", well: "stock", volume },
      { kind: "aspirate", well: "stock", volume },
      { kind: "dispense", well: "A1", volume },
      { kind: "drop", well: "stock", volume },
    ],
  };
}

export function stepExplanation(index: number, volume: number, source: number) {
  return [
    {
      title: "取一个新吸头",
      english: "Pick up tip",
      why: "液体接触吸头，而不是移液器内部。先取头是吸液的前置条件。",
      expect: "吸头状态从未安装变成已安装，三个位置的液量都不变。",
      object: "tips",
      before: "吸头架还有未使用的吸头，移液器上没有旧吸头。",
    },
    {
      title: `吸取 ${volume} µL`,
      english: "Aspirate",
      why: "这一步只把液体从源容器移到吸头里，还没有送到目标孔。",
      expect: `源容器 ${source - volume} µL · 吸头 ${volume} µL · 目标孔 0 µL。`,
      object: "stock",
      before: `已经安装新吸头，源容器至少有 ${volume} µL 可用液体。`,
    },
    {
      title: `排出 ${volume} µL`,
      english: "Dispense",
      why: "移液器到达目标孔后，将吸头中的液体转移到孔里。",
      expect: `源容器 ${source - volume} µL · 吸头 0 µL · 目标孔 ${volume} µL。`,
      object: "plate",
      before: `吸头中有 ${volume} µL 液体，目标为孔板 A1 孔。`,
    },
    {
      title: "弃去用过的吸头",
      english: "Discard tip",
      why: "结束本次转移，避免把已经使用的吸头带入下一次练习。",
      expect: "移液器不再带吸头，液体已经全部排入目标孔。",
      object: "waste",
      before: "已完成排液，吸头中没有残留的模型液体。",
    },
  ][Math.min(index, 3)];
}
