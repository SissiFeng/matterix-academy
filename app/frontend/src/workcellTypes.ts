import type { Session } from "./types";

export const workspaceViews = [
  "overview",
  "onboard",
  "twin",
  "readiness",
  "runs",
] as const;
export type WorkspaceView = (typeof workspaceViews)[number];
export const workspaceLabels: Record<string, string> = {
  overview: "Overview",
  onboard: "Onboard",
  twin: "Twin",
  readiness: "Sim → Real",
  runs: "Runs",
};
export const capabilityLabels: Record<string, string> = {
  pickup: "Pick up tip",
  aspirate: "Aspirate",
  dispense: "Dispense",
  drop: "Discard tip",
  mix: "Mix",
  move_labware: "Move labware",
  image: "Image",
};
export const connections: Record<string, { name: string; detail: string }> = {
  native_api: {
    name: "Native API",
    detail: "Plan a direct vendor API connection.",
  },
  pylabrobot: {
    name: "PyLabRobot",
    detail: "Plan a supported laboratory automation adapter.",
  },
  sila2: {
    name: "SiLA 2 connector",
    detail: "Plan a capability-based instrument connection.",
  },
  custom: {
    name: "Custom adapter",
    detail: "Document an adapter that still needs qualification.",
  },
};
export type DeviceDraft = {
  name: string;
  workcell: string;
  model: "opentrons_flex" | "opentrons_ot2";
  connection: string;
  capabilities: string[];
  stage: number;
};
export type ReadinessCheck = {
  id: string;
  label: string;
  status: "passed" | "failed" | "missing";
  detail: string;
  scope: "teaching" | "physical";
};
export type Device = DeviceDraft & {
  id: string;
  version: number;
  updated_at: string;
  twin_session_id: string | null;
  session: Session | null;
  checks: ReadinessCheck[];
  physical_ready: boolean;
  physical_state: null;
  instrument_id: string | null;
  evidence: "physical" | "synthetic" | "declaration_only";
};
export function draftOf(device?: Device): DeviceDraft {
  return device
    ? {
        name: device.name,
        workcell: device.workcell,
        model: device.model,
        connection: device.connection,
        capabilities: device.capabilities,
        stage: device.stage,
      }
    : {
        name: "",
        workcell: "My workcell",
        model: "opentrons_flex",
        connection: "",
        capabilities: [],
        stage: 1,
      };
}
