export type ConnectorInstrument = "flex" | "ot2";
export type ConnectorPlatform = "macos" | "linux" | "windows";

export type ConnectorRelease = {
  instrument: ConnectorInstrument;
  name: string;
  repository: string;
  source_commit: string;
  version: string;
  status: "candidate" | "approved" | "unavailable";
  reason: string;
  platforms: ConnectorPlatform[];
  release_id: string | null;
  artifact_sha256: string | null;
  execution_transport: string;
  download_url: string | null;
};
export type ConnectorCatalog = {
  schema: string;
  companion: {
    status: "source-only" | "available";
    version: string;
    platforms: ConnectorPlatform[];
    download_url: string | null;
    reason: string;
    artifact_sha256?: string | null;
  };
  releases: ConnectorRelease[];
};
export type InstrumentConnection = {
  id: string;
  version: number;
  instrument: ConnectorInstrument;
  display_name: string;
  platform: ConnectorPlatform;
  status: "unpaired" | "pairing" | "paired" | "revoked";
  created_at: number;
  updated_at: number;
  installation_id: string | null;
  probe: {
    instrument: ConnectorInstrument;
    serial: string;
    release_id: string;
    artifact_sha256: string;
    profile_sha256: string;
    source_commit: string;
    firmware: string;
    capabilities: string[];
    reachable: boolean;
    observed_at: number;
  } | null;
  qualified: boolean;
  active_run_id: string | null;
  approved_release: Record<string, unknown> | null;
};
export type ConnectorPreflight = {
  ready: boolean;
  enabled: boolean;
  connection_id: string;
  session_id: string;
  session_version: number | null;
  plan_hash: string | null;
  native_run_id: string | null;
  issues: { code: string; message: string }[];
};
export type PhysicalRun = {
  run_id: string;
  connection_id: string;
  version: number;
  status: "queued" | "claimed" | "completed" | "failed" | "stopped" | "unknown";
  session_id: string;
  native_run_id: string;
  plan_hash: string;
  instrument: ConnectorInstrument;
  created_at: number;
  updated_at: number;
  stop_requested: boolean;
  receipt: Record<string, unknown> | null;
  reason: string | null;
  resolution?: {
    request: {
      expected_version: number;
      resolution_id: string;
      connection_id: string;
      installation_id: string;
      plan_hash: string;
      instrument: ConnectorInstrument;
      protocol_id: string | null;
      robot_run_id: string | null;
      no_run_created: boolean;
      stopped: boolean;
      released: boolean;
      operator_id: string;
      evidence_sha256: string;
      detail: string;
    };
    resolved_at: number;
    historical_status: "unknown";
    replay_authorized: false;
  } | null;
};
