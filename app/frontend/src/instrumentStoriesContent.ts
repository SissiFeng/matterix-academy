import { STUDIO_LAYOUTS } from "./studioContent";

export type StoryInstrument = "flex" | "ot2";
export type StoryWorkflow = "transfer" | "distribute" | "dilution";
export type StoryStarter = StoryWorkflow | "blank";

export const STORY_DURATION = 36;

export const storyInstruments: Record<
  StoryInstrument,
  { name: string; shortName: string; description: string; deck: string }
> = {
  flex: {
    name: "Opentrons Flex",
    shortName: "Flex",
    description: "A modular deck. Room to build your next idea.",
    deck: "Lettered rows · numbered columns",
  },
  ot2: {
    name: "Opentrons OT-2",
    shortName: "OT-2",
    description: "A compact liquid handler. A clear place to begin.",
    deck: "Numbered slots · front to back",
  },
};

export const storyWorkflows: Record<
  StoryWorkflow,
  { label: string; description: string; detail: string }
> = {
  transfer: {
    label: "Transfer",
    description: "One source. One destination.",
    detail: "Move a measured volume from stock into a sample well.",
  },
  distribute: {
    label: "Distribute",
    description: "One source. Several samples.",
    detail: "Share liquid across several wells in measured portions.",
  },
  dilution: {
    label: "Serial dilution",
    description: "A little less concentrated, each time.",
    detail:
      "Add stock to buffer, then pass a portion to the next well with a fresh tip. The teaching model mixes each well instantly; colors represent a synthetic tracer.",
  },
};

export const storyChapters = [
  { at: 0, label: "Meet the instrument" },
  { at: 5, label: "Read the deck" },
  { at: 10, label: "Pick up a tip" },
  { at: 14, label: "Take up liquid" },
  { at: 20, label: "Make a workflow" },
  { at: 29, label: "Discard the tip" },
  { at: 33, label: "Make it yours" },
] as const;

export function storyChapterAt(time: number): number {
  return storyChapters.reduce(
    (chapter, entry, index) => (time >= entry.at ? index : chapter),
    0,
  );
}

export function storyCaption(
  instrument: StoryInstrument,
  workflow: StoryWorkflow,
  chapter: number,
): { heading: string; body: string; detail: string } {
  const flex = instrument === "flex";
  const workflowContent = storyWorkflows[workflow];
  const layout = STUDIO_LAYOUTS[instrument];
  return (
    [
      {
        heading: flex ? "Meet Flex." : "Meet OT-2.",
        body: flex
          ? "A pipette moves above a modular deck. A touchscreen sits beside the workspace, where labware holds your samples and supplies."
          : "Inside the enclosure, a moving gantry carries the pipette over a compact deck. Each item of labware has its own numbered position.",
        detail: flex
          ? "Flex can also use an optional gripper. This lesson explores pipetting only."
          : "This lesson uses a single-channel pipette to make each liquid movement easy to follow.",
      },
      {
        heading: "Every item has an address.",
        body: flex
          ? `Read Flex slots from A at the back to D at the front, with columns 1–3. Our tips are in ${layout.tips}, stock in ${layout.stock}, samples in ${layout.plate}, and trash in ${layout.waste}.`
          : `OT-2 slots run from 1–3 at the front to 10–11 at the back. Position 12 holds fixed trash. Our tips are in ${layout.tips}, stock in ${layout.stock}, and samples in ${layout.plate}.`,
        detail:
          "A tip rack holds disposable tips. Sample labware holds liquid. They have different jobs.",
      },
      {
        heading: "First, pick up a tip.",
        body: "The pipette lowers onto a disposable tip in the rack. Liquid travels inside this tip, keeping the pipette itself separate from the sample.",
        detail: "In the teaching model, a liquid step needs an attached tip.",
      },
      {
        heading: "Take up a measured volume.",
        body: "The tip enters the stock. Aspirating draws liquid into the tip; dispensing releases it somewhere else. The colored path shows where it moves.",
        detail:
          "Volume is measured in microliters: µL. Motion and liquid levels here are illustrative.",
      },
      {
        heading: workflowContent.description,
        body: workflowContent.detail,
        detail:
          workflow === "dilution"
            ? "This starter uses three fresh tips. Instant, ideal mixing is a teaching assumption; physical mixing and contamination control need separate validation."
            : "Choose a different workflow below, then adapt the same building blocks in the studio.",
      },
      {
        heading: "Finish with an empty pipette.",
        body: "After dispensing, the used tip goes into the trash. A complete teaching workflow leaves no liquid in the pipette and no tip attached.",
        detail:
          "The studio checks liquid accounting and cleanup, not experimental success.",
      },
      {
        heading: "Now, follow your own idea.",
        body: "Start with this workflow. Add steps, choose wells, change volumes, and watch your design run. Make a mistake, reset, and try something new.",
        detail:
          "The studio is a synthetic learning space. It does not control either instrument.",
      },
    ][chapter] ?? { heading: "", body: "", detail: "" }
  );
}
