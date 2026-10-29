export type MixingPlan = {
  course_id: "flex-mixing";
  title: string;
  seed: number;
  actions: {
    kind: "uncover" | "transfer";
    source_index: number | null;
    tip_id: string | null;
    volume_ul: number | null;
  }[];
};
export type SimulationSession = {
  id: string;
  version: number;
  experiment: MixingPlan;
  remote_active_run: string | null;
};
export type MixingState = {
  source_volumes_ul: number[];
  mixture_components_ul: number[];
  source_order: number[];
  lid_parked: boolean;
  lid_attached: boolean;
  active_tip: string | null;
  tips_used: string[];
  tips_discarded: string[];
  joint_positions: number[];
  native_action_index: number;
  native_action_count: number;
  native_action: string;
};
export type SimulationRun = {
  gpu?: GpuStatus | null;
  run_id: string;
  session_id: string;
  version: number;
  status: string;
  plan_hash: string;
  completed_steps: number;
  total_steps: number;
  stale_seconds: number;
  reason?: string;
  cleanup: { reset_verified: boolean; never_started?: boolean } | null;
  snapshot: {
    session_id: string;
    run_id: string;
    plan_hash: string;
    sequence: number;
    status: string;
    observed_at: string;
    engine_version: string;
    asset_version: string;
    error: string | null;
    steps: { index: number; status: string }[];
    native_state: {
      revision: number;
      observed_at: string;
      simulation_tick: number;
      pipette_volume_ul: number | null;
      tip_attached: boolean | null;
      well_volumes_ul: Record<string, number | null>;
      mixing: MixingState | null;
      studio?: {
        instrument: "flex" | "ot2";
        scene: "workflow-studio-flex" | "workflow-studio-ot2";
        observation_model: "native-semantic";
        labware_slots: Record<"tips" | "stock" | "plate" | "waste", string>;
        waste_volume_ul: number;
        native_action_index: number;
        native_action_count: number;
        native_action: string;
      } | null;
    } | null;
  } | null;
};
export type GpuStatus = {
  state: string;
  message: string;
  idle_seconds: number;
  retry_at: number | null;
  updated_at: number | null;
};
export const terminalRuns = new Set([
  "completed",
  "failed",
  "cancelled",
  "outcome_unknown",
]);
