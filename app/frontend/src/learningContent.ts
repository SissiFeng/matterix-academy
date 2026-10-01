import type { Experiment, LearningProgress } from "./types";

export const PHASES = [
  {
    id: "orient",
    title: "Explore the equipment",
    detail: "Connect your manual skills to Flex",
  },
  {
    id: "prepare",
    title: "Prepare the deck",
    detail: "Check labware, positions and liquids",
  },
  {
    id: "predict",
    title: "Predict changes",
    detail: "Think about where the liquid will go",
  },
  {
    id: "run",
    title: "Run step by step",
    detail: "Observe the result of each action",
  },
  {
    id: "reflect",
    title: "Reflect and retry",
    detail: "Test your understanding with a new volume",
  },
] as const;

export const EQUIPMENT = {
  pipette: {
    name: "Pipette",
    purpose:
      "Draws in and dispenses liquid, just like a handheld pipette. The robot moves it between locations.",
    notice:
      "Check the volume range and tip compatibility first. This teaching model has a 300 µL limit; that is not a specification for every Flex pipette.",
    manual: "By hand: set the pipette volume",
    robot: "With Flex: specify the volume and target well in each action",
  },
  tips: {
    name: "Tip rack",
    purpose:
      "Holds disposable tips. The pipette must pick up a tip before handling liquid.",
    notice:
      "Use a fresh tip for each transfer in this lesson. Other protocols need a tip strategy based on contamination risk.",
    manual: "By hand: attach a fresh tip",
    robot: "With Flex: add a Pick up tip action first",
  },
  stock: {
    name: "Source container",
    purpose: "Holds the practice liquid. This is where your transfer begins.",
    notice:
      "The robot needs an initial volume. These values come from the teaching model, not a liquid-level sensor.",
    manual: "By hand: find the reagent and check how much remains",
    robot: "With Flex: specify the source container, well and starting volume",
  },
  plate: {
    name: "Target plate",
    purpose:
      "Receives liquid. Each well has an address, such as A1 or A2. The plate itself occupies a deck slot.",
    notice:
      "Slot D2 → target plate → well A1. Deck slots and plate wells are different levels of location.",
    manual: "By hand: move the tip to the target well",
    robot: "With Flex: specify the labware and well address",
  },
  waste: {
    name: "Waste chute",
    purpose:
      "Receives used tips. The Flex waste chute is installed at deck position D3.",
    notice:
      "The waste chute is fixed at D3. It is different from the movable trash bin.",
    manual: "By hand: eject the used tip into a waste container",
    robot: "With Flex: add Discard tip after the transfer",
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
    title: "Pipette and tips",
    detail:
      "Confirm that tips are available and the transfer is within the 1–300 µL range of this teaching pipette.",
  },
  {
    id: "labware",
    title: "Labware and positions",
    detail:
      "The source, plate and tip rack each occupy one slot. The waste chute is at D3. Well A1 belongs to the target plate.",
  },
  {
    id: "liquids",
    title: "Starting volumes",
    detail:
      "The source starts with 1,000 µL and the target well is empty. This is a direct transfer, so no diluent is needed.",
  },
  {
    id: "simulation",
    title: "Scope of this exercise",
    detail:
      "This teaching model does not simulate collisions, liquid height or real pipetting accuracy. No physical robot is connected.",
  },
];

export function firstTransfer(volume = 100): Experiment {
  return {
    title: `First transfer · ${volume} µL`,
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
      title: "Pick up a fresh tip",
      english: "Pick up tip",
      why: "Liquid goes into the tip, not the pipette body. A tip must be attached before aspiration.",
      expect:
        "A tip becomes attached. Volumes in the source, tip and target do not change.",
      object: "tips",
      before: "An unused tip is available and no tip is currently attached.",
    },
    {
      title: `Aspirate ${volume} µL`,
      english: "Aspirate",
      why: "Aspiration moves liquid from the source into the tip. The target well has not received any liquid yet.",
      expect: `Source ${source - volume} µL · Tip ${volume} µL · Target 0 µL.`,
      object: "stock",
      before: `A fresh tip is attached and the source has at least ${volume} µL available.`,
    },
    {
      title: `Dispense ${volume} µL`,
      english: "Dispense",
      why: "At the target well, the pipette releases the liquid held in its tip.",
      expect: `Source ${source - volume} µL · Tip 0 µL · Target ${volume} µL.`,
      object: "plate",
      before: `The tip contains ${volume} µL and the destination is well A1 of the plate.`,
    },
    {
      title: "Discard the used tip",
      english: "Discard tip",
      why: "Finish this transfer with no used tip attached, ready for the next exercise.",
      expect:
        "The pipette has no tip attached. All transferred liquid is in the target well.",
      object: "waste",
      before:
        "Dispensing is complete and no modeled liquid remains in the tip.",
    },
  ][Math.min(index, 3)];
}
