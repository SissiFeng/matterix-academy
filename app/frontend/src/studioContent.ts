import type { Action, Experiment } from "./types";

export type Instrument = "flex" | "ot2";
export type Starter = "transfer" | "distribute" | "dilution" | "blank";

export const INSTRUMENT_NAMES: Record<Instrument, string> = {
  flex: "Opentrons Flex",
  ot2: "Opentrons OT-2",
};

export const STUDIO_LAYOUTS: Record<
  Instrument,
  Record<"stock" | "plate" | "tips" | "waste", string>
> = {
  flex: { stock: "D1", plate: "D2", tips: "B1", waste: "D3" },
  ot2: { stock: "1", plate: "2", tips: "4", waste: "12" },
};

export const STARTERS: Record<Starter, { title: string; description: string }> =
  {
    transfer: {
      title: "Transfer",
      description: "Move 100 µL from a stock solution into one well.",
    },
    distribute: {
      title: "Distribute",
      description: "Aspirate once, then share 240 µL across three wells.",
    },
    dilution: {
      title: "Serial dilution",
      description:
        "Transfer through three wells with fresh tips and ideal mixing.",
    },
    blank: {
      title: "Blank workflow",
      description: "Choose your own steps, volumes and destinations.",
    },
  };

const action = (
  kind: Action["kind"],
  well: Action["well"] = "stock",
  volume = 100,
): Action => ({ kind, well, volume });

export function makeStudioExperiment(
  instrument: Instrument,
  starter: Starter,
): Experiment {
  const actions: Action[] =
    starter === "blank"
      ? []
      : starter === "distribute"
        ? [
            action("pickup"),
            action("aspirate", "stock", 240),
            ...(["A1", "A2", "A3"] as const).map((well) =>
              action("dispense", well, 80),
            ),
            action("drop"),
          ]
        : starter === "dilution"
          ? (["stock", "A1", "A2"] as const).flatMap((source, index) => [
              action("pickup"),
              action("aspirate", source),
              action("dispense", (["A1", "A2", "A3"] as const)[index]),
              action("drop"),
            ])
          : [
              action("pickup"),
              action("aspirate"),
              action("dispense", "A1"),
              action("drop"),
            ];
  return {
    title: `${INSTRUMENT_NAMES[instrument]} · ${STARTERS[starter].title}`,
    course_id: "workflow-sandbox",
    instrument,
    layout: { ...STUDIO_LAYOUTS[instrument] },
    source_volume: 1000,
    diluent_volume: starter === "dilution" ? 100 : 0,
    actions,
  };
}

export const ACTION_LABELS: Record<Action["kind"], string> = {
  pickup: "Pick up tip",
  aspirate: "Aspirate",
  dispense: "Dispense",
  drop: "Discard tip",
};

export const ACTION_HINTS: Record<Action["kind"], string> = {
  pickup: "Attach a fresh tip before drawing liquid.",
  aspirate: "Draw liquid from the selected container into the tip.",
  dispense: "Release liquid from the tip into the selected container.",
  drop: "Discard the tip and any liquid left inside it.",
};
