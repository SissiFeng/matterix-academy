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
  /** Drawn deck slots in the twin's local frame (metres); empty: one top access point. */
  sites?: Site[];
  /** Transfer twins: the arm profile and joint limits narrowed by its connector. */
  arm?: ArmProfile | null;
  joint_limits_deg?: number[];
};
export type Site = { key: string; x: number; z: number };
export type ArmProfile = "ur3e" | "ur5e" | "ur10e";
export const armProfiles: { key: ArmProfile; name: string; reach: number }[] = [
  { key: "ur3e", name: "UR3e", reach: 0.5 },
  { key: "ur5e", name: "UR5e", reach: 0.85 },
  { key: "ur10e", name: "UR10e", reach: 1.3 },
];
/** Slot names a sample can take: drawn slots, else numbered ones. */
export const siteKeys = (spec: TwinSpec) =>
  spec.sites?.length
    ? spec.sites.map((s) => s.key)
    : Array.from({ length: spec.resource.slots }, (_, i) => String(i + 1));
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
  /** The axis the model stands on; a Z-up model is turned to the scene's Y up. */
  up?: "y" | "z";
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
  /** Instrument lesson in Meet the instruments, when there is one. */
  lesson?: "flex" | "ot2" | null;
};
export type LibraryResults = {
  size: number;
  total: number;
  results: LibraryEntry[];
};
/** A library entry drawn with its own 3D model, for the model library page. */
export type ModelEntry = LibraryEntry & { mesh: Mesh; url: string };
export type ModelResults = {
  size: number;
  total: number;
  domains: Record<string, number>;
  results: ModelEntry[];
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
  /** Where the dimensions come from; a layout is as trustworthy as its weakest twin. */
  size_basis?: "checked" | "catalogued" | "estimated";
};
export type Step = {
  device_id: string;
  operation: Operation;
  source_id: string | null;
  target_id: string | null;
  value: number;
  /** Tracked sample the step acts on; "sample" when the workflow tracks one. */
  sample?: string;
  /** Slots used; empty takes the first free one. */
  site?: string;
  source_site?: string;
  target_site?: string;
};
export const DEFAULT_SAMPLE = "sample";
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
  /** Arm time at the connector's default speed, simulated when `simulation` is present. */
  seconds?: number;
  source_site?: string | null;
  target_site?: string | null;
  /** Least elbow bend while lowering into a station. */
  elbow_deg?: number;
  /** Present when the path was run in the rigid-body simulation. */
  simulation?: {
    engine: "mujoco";
    version: string;
    speed: number;
    payload_kg: number;
    tracking_deg: number;
    torque_ratio: number;
    self_clearance_m: number;
    nearest: string | null;
    kinematic_seconds: number;
    kinematic_clearance_m: number;
  };
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
  /** What arm paths are simulated with; null when only the geometry is checked. */
  simulation: {
    engine: "mujoco";
    version: string;
    speed: number;
    payload_kg: number;
  } | null;
};
export type LayoutMetrics = {
  run_s: number;
  arm_s: number;
  path_m: number;
  clearance_m: number;
  reach_margin_m: number;
  elbow_deg: number;
  area_m2: number;
};
export type LayoutCandidate = LayoutMetrics & {
  layout: Layout;
  motions: MotionSummary[];
  /** Slots the arm reaches on instruments with a slot preference. */
  slots: Record<string, string[]>;
};
export type Diagnosis = { kind: string; count: number; hint: string };
export type Consolidation = {
  drop_id: string;
  into_id: string;
  extra_slots: number;
  free_slots: number;
  transfers_saved: number;
  message: string;
};
export type LayoutSearchChunk = {
  arm: string;
  reach_m: number;
  total: number;
  next: number | null;
  candidates: LayoutCandidate[];
  checked: number;
  failure: string | null;
  diagnosis: Diagnosis[];
  /** Only on the first chunk. */
  consolidation?: Consolidation[];
};
export type Side = "left" | "right" | "front" | "back";
export type Constraint = {
  kind: "reach_slots" | "zone" | "near" | "apart" | "exclude";
  twin_id: string;
  other_id?: string | null;
  count?: number;
  side?: Side | null;
  metres?: number;
};
export type BriefRole = {
  key: string;
  name: string;
  operations: Operation[];
  vessel: Vessel;
  query: string;
  reach_slots?: number;
};
export type BriefStep = {
  role: string;
  operation: Operation;
  source_role: string;
  target_role: string;
  value: number;
  sample?: string;
};
export type BriefPreference = {
  kind: "zone" | "near" | "apart";
  role: string;
  other_role: string;
  side: Side | "";
  metres: number;
};
export type Brief = {
  id: string;
  text: string;
  status: "starting" | "generating" | "draft" | "failed" | "submission_unknown";
  /** "import" when the draft came from a workflow file. */
  source?: "import";
  message: string;
  draft: {
    roles: BriefRole[];
    steps: BriefStep[];
    assumptions: string[];
    preferences?: BriefPreference[];
  } | null;
  bindings: Record<string, string>;
};
export type TraceStep = {
  step: number;
  device_id: string;
  operation: Operation;
  sample?: string;
  site?: string | null;
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
  constraints: Constraint[];
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
