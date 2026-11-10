import type { Instrument, Starter } from "./studioContent";

export type Robot = "Flex" | "OT-2";
export type Media = {
  kind: "image" | "video";
  src: string;
  alt: string;
  credit: string;
};

export const robotParts: {
  name: string;
  job: string;
  robots: Robot[];
  media?: Media;
}[] = [
  {
    name: "Pipette",
    job: "Draws liquid into a disposable tip and releases it somewhere else. Single-channel pipettes work one well at a time; 8-channel pipettes fill a column.",
    robots: ["Flex", "OT-2"],
  },
  {
    name: "Gantry",
    job: "The moving frame that carries the pipette left, right, forward, back, up and down above the deck.",
    robots: ["Flex", "OT-2"],
  },
  {
    name: "Deck and labware",
    job: "Numbered or lettered slots hold labware: tip racks, well plates, reservoirs and tube racks.",
    robots: ["Flex", "OT-2"],
  },
  {
    name: "Trash",
    job: "Collects used tips so the next step starts clean.",
    robots: ["Flex", "OT-2"],
  },
  {
    name: "Gripper",
    job: "Picks up a plate and moves it to another slot or module, so you do not have to.",
    robots: ["Flex"],
  },
];

export type Capability =
  "heat" | "cool" | "shake" | "magnet" | "cycle" | "read" | "store";
export const capabilityNames: Record<Capability, string> = {
  heat: "Heat",
  cool: "Cool",
  shake: "Shake",
  magnet: "Magnets",
  cycle: "Thermal cycling",
  read: "Measure",
  store: "Store plates",
};
export const capabilityOrder: Capability[] = [
  "heat",
  "cool",
  "shake",
  "magnet",
  "cycle",
  "read",
  "store",
];

export const modules: {
  name: string;
  does: Capability[];
  robots: Robot[];
  note: string;
  media?: Media;
}[] = [
  {
    name: "Heater-Shaker",
    does: ["heat", "shake"],
    robots: ["Flex", "OT-2"],
    note: "The only module that shakes. It heats but cannot cool.",
  },
  {
    name: "Temperature Module",
    does: ["heat", "cool"],
    robots: ["Flex", "OT-2"],
    note: "Holds a plate or tubes at a set temperature. GEN2 is the current version.",
  },
  {
    name: "Thermocycler",
    does: ["heat", "cool", "cycle"],
    robots: ["Flex", "OT-2"],
    note: "Repeats heating and cooling steps with a heated lid, as in PCR.",
  },
  {
    name: "Magnetic Module",
    does: ["magnet"],
    robots: ["OT-2"],
    note: "Raises magnets under a plate to pull beads aside. No heating.",
  },
  {
    name: "Magnetic Block",
    does: ["magnet"],
    robots: ["Flex"],
    note: "Unpowered magnets for Flex. Plates go on and off by hand or with the gripper.",
  },
  {
    name: "Absorbance Plate Reader",
    does: ["read"],
    robots: ["Flex"],
    note: "Measures how much light each well absorbs.",
  },
  {
    name: "Flex Stacker",
    does: ["store"],
    robots: ["Flex"],
    note: "Stores plates or tip racks and feeds them onto the deck.",
  },
];

export const unitOperations: {
  name: string;
  what: string;
  uses: string[];
  practice?: { instrument: Instrument; starter: Starter };
  media?: Media;
}[] = [
  {
    name: "Liquid transfer",
    what: "Pick up a tip, aspirate from one well, dispense into another, discard the tip.",
    uses: ["Pipette", "Tip rack", "Labware", "Trash"],
    practice: { instrument: "flex", starter: "transfer" },
  },
  {
    name: "Distribute",
    what: "Share one source across several wells in measured portions.",
    uses: ["Pipette", "Tip rack", "Labware"],
    practice: { instrument: "flex", starter: "distribute" },
  },
  {
    name: "Serial dilution",
    what: "Pass a portion from well to well so each is less concentrated than the last.",
    uses: ["Pipette", "Tip rack", "Labware"],
    practice: { instrument: "flex", starter: "dilution" },
  },
  {
    name: "Mix",
    what: "Aspirate and dispense in the same well, or shake the whole plate.",
    uses: ["Pipette", "Heater-Shaker"],
  },
  {
    name: "Incubate",
    what: "Hold samples at a temperature for a set time.",
    uses: ["Temperature Module", "Heater-Shaker"],
  },
  {
    name: "Thermal cycling",
    what: "Repeat temperature steps many times, for example to copy DNA.",
    uses: ["Thermocycler"],
  },
  {
    name: "Magnetic separation",
    what: "Hold magnetic beads in place while the pipette removes the liquid.",
    uses: ["Magnetic Module", "Magnetic Block", "Pipette"],
  },
  {
    name: "Move labware",
    what: "Carry a plate between slots and modules during a run.",
    uses: ["Gripper"],
  },
  {
    name: "Read a plate",
    what: "Measure every well and record the result.",
    uses: ["Absorbance Plate Reader", "Gripper"],
  },
];
