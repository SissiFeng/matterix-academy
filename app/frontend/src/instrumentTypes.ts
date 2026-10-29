export type Operation = "load" | "transfer" | "mix" | "heat" | "read" | "wait";
export const operations: Operation[] = [
  "load",
  "transfer",
  "mix",
  "heat",
  "read",
  "wait",
];
export const operationLabels: Record<Operation, string> = {
  load: "Load sample",
  transfer: "Transfer sample",
  mix: "Mix",
  heat: "Heat",
  read: "Read",
  wait: "Wait",
};
export type Layer =
  | "volume"
  | "resource"
  | "geometry"
  | "container"
  | "consumable"
  | "state"
  | "constraint";
export const layers: Layer[] = [
  "volume",
  "resource",
  "geometry",
  "container",
  "consumable",
  "state",
  "constraint",
];
export const layerLabels: Record<Layer, string> = {
  volume: "Volume",
  resource: "Resources (slots)",
  geometry: "Geometry",
  container: "Container",
  consumable: "Consumables",
  state: "State / operations",
  constraint: "Constraints",
};
export type Vessel = "none" | "tube" | "vial" | "plate" | "reservoir";
export const vessels: Vessel[] = ["none", "tube", "vial", "plate", "reservoir"];
export type Consumable = {
  name: string;
  used_by: Operation;
  per_use: number;
  stock: number;
};
export type Vec = [number, number, number];
export type TwinSpec = {
  name: string;
  parts: { size: Vec; position: Vec; color: string }[];
  operations: Operation[];
  container: { vessel: Vessel; max_volume_ul: number };
  resource: { slots: number };
  consumables: Consumable[];
  limits: { min_temp_c: number; max_temp_c: number; max_duration_s: number };
  assumptions: string;
};
export type Residual = {
  id: string;
  created_at: string;
  layer: Layer;
  step: number | null;
  predicted: string;
  observed: string;
  note: string;
  revision: number;
  resolved_in: number | null;
  evidence: "learner_observation";
};
export type Twin = {
  id: string;
  status:
    | "starting"
    | "generating"
    | "draft"
    | "ready"
    | "failed"
    | "submission_unknown";
  confirmed: boolean;
  mode: "mock" | "real";
  source: "astra_image" | "academy_template";
  spec: TwinSpec | null;
  message: string;
  evidence: "synthetic";
  revision: number;
  residuals: Residual[];
};
export type Step = {
  device_id: string;
  operation: Operation;
  source_id: string | null;
  target_id: string | null;
  value: number;
};
export type TraceStep = {
  step: number;
  device_id: string;
  operation: Operation;
  location: string | null;
  vessel: Vessel | null;
  volume_ul: number;
  temperature_c: number;
  mixed: boolean;
  elapsed_s: number;
  consumables: Record<string, Record<string, number>>;
  measurement: {
    kind: string;
    temperature_c: number;
    volume_ul: number;
    mixed: boolean;
  } | null;
};
export type InstrumentRun = {
  id: string;
  created_at: string;
  evidence: "synthetic";
  connector: "mock_sila2";
  steps: Step[];
  twins: { id: string; name: string; revision: number }[];
  trace: TraceStep[];
  status: "completed";
};
export type InstrumentCatalog = {
  version: number;
  twins: Twin[];
  steps: Step[];
  runs: InstrumentRun[];
  templates: Record<string, TwinSpec>;
  astra_available: boolean;
  real_available: boolean;
  real_reason: string;
};
export type ConnectorPackage = {
  device_id: string;
  evidence: "synthetic";
  files: Record<string, string>;
};
