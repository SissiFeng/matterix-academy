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
/** The registered model drawn in place of the planning box. */
export type Mesh = {
  kind: "glb" | "ot2" | "balance" | "ur5e";
  url?: string;
  sha256?: string;
  up?: "z";
  asset?: string;
};
export type SimReadyProvenance = {
  id: string;
  mesh?: Mesh | null;
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
  collection: "workcell" | "simready" | "chemlab";
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
    | "astra_image"
    | "academy_template"
    | "simready_asset"
    | "chemlab_asset"
    | "workcell_asset";
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
  /** Stays put when layouts are searched. */
  kept?: boolean;
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
  /** Arm time at the connector's default speed; absent on older runs. */
  seconds?: number;
};
export type Motion = MotionSummary & {
  frames: ArmFrame[];
  /** Joint angles (rad) of the same frames. */
  joints: number[][];
};
export type BlockedMotion = {
  step: number;
  actor_id: string;
  source_id: string;
  target_id: string;
  arm: string;
  blocked_by: string | null;
  link: string | null;
  frames: ArmFrame[];
  joints: number[][];
};
export type LayoutPreview = {
  arm: string;
  reach_m: number;
  motions: Motion[];
  error: { message: string; layer: string } | null;
  blocked: BlockedMotion | null;
};
export type LayoutMetrics = {
  run_s: number;
  arm_s: number;
  path_m: number;
  clearance_m: number;
  reach_margin_m: number;
  area_m2: number;
};
export type LayoutCandidate = LayoutMetrics & {
  layout: Layout;
  motions: MotionSummary[];
};
export type LayoutSearchChunk = {
  arm: string;
  total: number;
  next: number | null;
  candidates: LayoutCandidate[];
  checked: number;
  failure: string | null;
};
export type BriefRole = {
  key: string;
  name: string;
  operations: Operation[];
  vessel: Vessel;
  query: string;
};
export type BriefStep = {
  role: string;
  operation: Operation;
  source_role: string;
  target_role: string;
  value: number;
};
export type Brief = {
  id: string;
  text: string;
  status: "starting" | "generating" | "draft" | "failed" | "submission_unknown";
  message: string;
  draft: {
    roles: BriefRole[];
    steps: BriefStep[];
    assumptions: string[];
  } | null;
  bindings: Record<string, string>;
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
  brief: Brief | null;
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
