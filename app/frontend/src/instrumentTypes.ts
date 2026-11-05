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
export type SimReadyProvenance = {
  id: string;
  label: string;
  provider: string;
  license: string;
  attribution: string;
  repo: string;
  revision: string;
  path: string;
  url: string;
};
export type SimReadyAsset = Omit<SimReadyProvenance, "id"> & {
  spec: TwinSpec;
};
export type LibraryEntry = {
  collection: "simready" | "chemlab";
  id: string;
  name: string;
  label: string;
  provider: string;
  domain: string;
  license: string;
  attribution: string;
  size_m: [number, number, number];
  operations: Operation[];
};
export type LibraryResults = {
  size: number;
  total: number;
  results: LibraryEntry[];
};
export type LibraryMatch = LibraryEntry & {
  suggested_by: "astra" | "label_text";
  verified: boolean;
};
export type Identification = {
  library_id: string;
  alternatives: string[];
  maker: string;
  model: string;
  confidence: "high" | "medium" | "low";
  evidence: string;
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
  source:
    "astra_image" | "academy_template" | "simready_asset" | "chemlab_asset";
  asset?: SimReadyProvenance | null;
  identification?: Identification | null;
  matches?: LibraryMatch[];
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
export type Access = "top" | "front";
export type Placement = {
  twin_id: string;
  x: number;
  z: number;
  yaw: number;
  access: Access;
};
export type Bench = { width: number; depth: number };
export type Layout = { bench: Bench; placements: Placement[] };
/** World points (y-up, metres) of the arm base, six joints and the grasp point. */
export type ArmFrame = Vec[];
export type MotionSummary = {
  step: number;
  actor_id: string;
  source_id: string;
  target_id: string;
  arm: string;
  planner: "swing" | "joint" | "rrt_connect";
  length_m: number;
  clearance_m: number;
};
export type Motion = MotionSummary & { frames: ArmFrame[] };
export type BlockedMotion = {
  step: number;
  actor_id: string;
  source_id: string;
  target_id: string;
  arm: string;
  blocked_by: string | null;
  link: string | null;
  frames: ArmFrame[];
};
export type LayoutPreview = {
  arm: string;
  reach_m: number;
  motions: Motion[];
  error: { message: string; layer: string } | null;
  blocked: BlockedMotion | null;
};
export type LayoutSuggestion = {
  layout: Layout;
  length_m: number;
  clearance_m: number;
  motions: MotionSummary[];
};
export type LayoutSuggestions = {
  arm: string;
  suggestions: LayoutSuggestion[];
  checked: number;
  error: { message: string; layer: string } | null;
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
  motion?: MotionSummary;
};
export type InstrumentRun = {
  id: string;
  created_at: string;
  evidence: "synthetic";
  connector: "in_process_mock" | "mock_sila2";
  steps: Step[];
  twins: { id: string; name: string; revision: number; spec?: TwinSpec }[];
  trace: TraceStep[];
  status: "completed";
};
export type InstrumentCatalog = {
  version: number;
  twins: Twin[];
  steps: Step[];
  runs: InstrumentRun[];
  layout: Layout | null;
  templates: Record<string, TwinSpec>;
  simready: Record<string, SimReadyAsset>;
  astra_available: boolean;
  real_available: boolean;
  real_reason: string;
};
export type ConnectorPackage = {
  device_id: string;
  evidence: "synthetic";
  files: Record<string, string>;
};
