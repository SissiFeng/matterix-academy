import type { SimulationRun } from "./simulationTypes";

export type EvidenceRun = SimulationRun & {
  scene?: string;
  instrument?: string;
  commissioning?: boolean;
};
export type ServerReport = {
  grant_id: string;
  expires: number;
  worker_qualified: boolean;
  runs: {
    run: EvidenceRun;
    browser: {
      run_id: string;
      native_session_id: string;
      plan_hash: string;
      frames_decoded: number;
      source: string;
    } | null;
  }[];
};
type Binding = {
  run_id: string;
  session_id: string;
  plan_hash: string;
  native_session_id: string;
};
export type VideoReceipt = Binding & {
  client_id: string;
  frames_decoded: number;
  relay_verified: boolean;
  observed_at: number;
};
type ReadReceipt = Binding & {
  document_id: string;
  version: number;
  completed_steps: number;
  received_at: number;
};
type SubmissionReceipt = {
  run_id: string;
  session_id: string;
  expected_version: number;
  plan_hash: string;
  document_id: string;
};
export type EvidenceState = {
  schema: "academy.studio-browser-receipts/1";
  grant_id: string;
  history_missing: boolean;
  submissions: SubmissionReceipt[];
  reads: ReadReceipt[];
  videos: (VideoReceipt & { document_id: string })[];
  recoveries: (Binding & {
    before: string;
    after: string;
    minimum_version: number;
    observed_version: number;
    received_at: number;
  })[];
};
type Storage = Pick<globalThis.Storage, "getItem" | "setItem">;
const key = (grant: string) => `academy.studio-evidence.${grant}`;
const same = (a: Binding, b: Binding) =>
  a.run_id === b.run_id &&
  a.session_id === b.session_id &&
  a.plan_hash === b.plan_hash &&
  a.native_session_id === b.native_session_id;

export function readEvidence(
  storage: Storage,
  report: ServerReport,
): EvidenceState {
  const raw = storage.getItem(key(report.grant_id));
  if (!raw)
    return {
      schema: "academy.studio-browser-receipts/1",
      grant_id: report.grant_id,
      history_missing: report.runs.length > 0,
      submissions: [],
      reads: [],
      videos: [],
      recoveries: [],
    };
  const state = JSON.parse(raw) as EvidenceState;
  if (
    state.schema !== "academy.studio-browser-receipts/1" ||
    state.grant_id !== report.grant_id ||
    typeof state.history_missing !== "boolean" ||
    ![state.submissions, state.reads, state.videos, state.recoveries].every(
      Array.isArray,
    )
  )
    throw new Error(
      "Saved acceptance evidence could not be read. Preserve it for review.",
    );
  return state;
}

export function saveEvidence(storage: Storage, state: EvidenceState) {
  storage.setItem(key(state.grant_id), JSON.stringify(state));
}

/** This durable counter records attempted POSTs, including uncertain outcomes. */
export function recordSubmission(
  state: EvidenceState,
  receipt: SubmissionReceipt,
) {
  if (state.submissions.some((item) => item.run_id === receipt.run_id))
    throw new Error(
      "This native submission was already recorded. Recover the original run.",
    );
  return { ...state, submissions: [...state.submissions, receipt] };
}

/** Called only for a successful session GET initiated by this document. */
export function recordRead(
  state: EvidenceState,
  run: EvidenceRun,
  documentId: string,
  reloaded: boolean,
  receivedAt: number,
): EvidenceState {
  if (
    !run.snapshot ||
    run.snapshot.run_id !== run.run_id ||
    run.snapshot.plan_hash !== run.plan_hash
  )
    return state;
  const receipt: ReadReceipt = {
    run_id: run.run_id,
    session_id: run.session_id,
    plan_hash: run.plan_hash,
    native_session_id: run.snapshot.session_id,
    document_id: documentId,
    version: run.version,
    completed_steps: run.completed_steps,
    received_at: receivedAt,
  };
  const previous = state.reads.find((item) => item.run_id === run.run_id);
  let recoveries = state.recoveries;
  if (
    reloaded &&
    previous &&
    previous.document_id !== documentId &&
    same(previous, receipt) &&
    run.version >= previous.version &&
    run.completed_steps >= previous.completed_steps
  )
    recoveries = [
      ...recoveries,
      {
        run_id: run.run_id,
        session_id: run.session_id,
        plan_hash: run.plan_hash,
        native_session_id: run.snapshot.session_id,
        before: previous.document_id,
        after: documentId,
        minimum_version: previous.version,
        observed_version: run.version,
        received_at: receivedAt,
      },
    ];
  if (previous?.document_id === documentId && previous.version > run.version)
    return state;
  return {
    ...state,
    reads: [
      ...state.reads.filter((item) => item.run_id !== run.run_id),
      receipt,
    ],
    recoveries,
  };
}

export function recordVideo(
  state: EvidenceState,
  receipt: VideoReceipt,
  documentId: string,
) {
  if (
    !Number.isSafeInteger(receipt.frames_decoded) ||
    receipt.frames_decoded <= 0
  )
    return state;
  // Keep observed successful evidence when a later connection stalls. Never infer success.
  const existing = state.videos.find(
    (item) => item.client_id === receipt.client_id,
  );
  if (
    existing &&
    (!same(existing, receipt) || existing.document_id !== documentId)
  )
    throw new Error("Viewport evidence changed identity.");
  if (existing?.relay_verified && !receipt.relay_verified) return state;
  return {
    ...state,
    videos: [
      ...state.videos.filter((item) => item.client_id !== receipt.client_id),
      {
        ...receipt,
        document_id: documentId,
      },
    ],
  };
}

/** Measure the selected transport of the peer carrying THIS video, not an old peer. */
export async function measureVideo(
  peer: RTCPeerConnection,
  video: HTMLVideoElement,
  baseline: number,
): Promise<{ frames_decoded: number; relay_verified: boolean } | null> {
  const carriesVideo = () =>
    peer.connectionState === "connected" &&
    video.srcObject instanceof MediaStream &&
    peer
      .getReceivers()
      .some(
        ({ track }) =>
          track?.kind === "video" &&
          track.readyState === "live" &&
          (video.srcObject as MediaStream).getVideoTracks().includes(track),
      );
  if (!carriesVideo()) return null;
  const stats = await peer.getStats();
  if (!carriesVideo()) return null;
  const frames = video.getVideoPlaybackQuality().totalVideoFrames - baseline;
  if (frames <= 0) return null;
  const selected = new Set(
    [...stats.values()]
      .filter((row) => row.type === "transport")
      .map((row) => row.selectedCandidatePairId)
      .filter(Boolean),
  );
  const relay = [...stats.values()].some(
    (row) =>
      row.type === "candidate-pair" &&
      selected.has(row.id) &&
      row.state === "succeeded" &&
      row.nominated === true &&
      stats.get(row.localCandidateId)?.candidateType === "relay" &&
      stats.get(row.remoteCandidateId)?.candidateType === "relay",
  );
  return { frames_decoded: frames, relay_verified: relay };
}

// Keep only known public report/receipt fields. Never export storage, auth, SDP,
// ICE servers, candidate addresses or signed media URLs, even if supplied as extras.
const reportFields = new Set([
  "grant_id",
  "expires",
  "worker_qualified",
  "runs",
  "run",
  "browser",
  "version",
  "run_id",
  "session_id",
  "native_session_id",
  "plan_hash",
  "status",
  "scene",
  "instrument",
  "commissioning",
  "completed_steps",
  "total_steps",
  "snapshot",
  "cleanup",
  "reset_verified",
  "command_id",
  "engine_version",
  "asset_version",
  "checks",
  "objects",
  "liquids",
  "tips",
  "controllers",
  "stopped",
  "release_verified",
  "source",
  "frames_decoded",
  "observed_at",
  "sequence",
  "session_revision",
  "engine",
  "evidence",
  "simulation_only",
  "steps",
  "index",
  "completed_at",
  "observation_revision",
  "native_state",
  "error",
  "revision",
  "simulation_tick",
  "pipette_volume_ul",
  "tip_attached",
  "well_volumes_ul",
  "stock",
  "A1",
  "A2",
  "A3",
  "mixing",
  "studio",
  "observation_model",
  "waste_volume_ul",
  "labware_slots",
  "plate",
  "waste",
  "native_action_index",
  "native_action_count",
  "native_action",
]);
function publicReport(report: ServerReport): ServerReport {
  return JSON.parse(
    JSON.stringify(report, (field, value) =>
      field === "" || /^\d+$/.test(field) || reportFields.has(field)
        ? value
        : undefined,
    ),
  );
}

function receiptProof(state: EvidenceState) {
  const fields = new Set([
    "submissions",
    "reads",
    "videos",
    "recoveries",
    "run_id",
    "session_id",
    "plan_hash",
    "native_session_id",
    "document_id",
    "expected_version",
    "version",
    "completed_steps",
    "received_at",
    "client_id",
    "frames_decoded",
    "relay_verified",
    "observed_at",
    "before",
    "after",
    "minimum_version",
    "observed_version",
  ]);
  return JSON.parse(
    JSON.stringify(state, (field, value) =>
      field === "" || /^\d+$/.test(field) || fields.has(field)
        ? value
        : undefined,
    ),
  );
}

export function acceptanceReport(state: EvidenceState, server: ServerReport) {
  const issues: string[] = [];
  if (state.grant_id !== server.grant_id)
    issues.push("Commissioning grant changed.");
  if (state.history_missing)
    issues.push("Earlier browser receipts are missing.");
  if (state.submissions.length !== 2 || server.runs.length !== 2)
    issues.push(
      "Exactly two recorded native submissions and server runs are required.",
    );
  const runs = server.runs.map(({ run, browser }, index) => {
    const submission = state.submissions[index];
    const binding: Binding = {
      run_id: run.run_id,
      session_id: run.session_id,
      plan_hash: run.plan_hash,
      native_session_id: run.snapshot?.session_id ?? "",
    };
    const videos = state.videos.filter(
      (video) =>
        same(video, binding) &&
        video.relay_verified &&
        video.frames_decoded > 0,
    );
    const recovery = state.recoveries.find(
      (item) =>
        same(item, binding) &&
        item.observed_version >= item.minimum_version &&
        videos.some(
          (video) =>
            video.document_id === item.before &&
            video.observed_at <= item.received_at,
        ) &&
        videos.some(
          (video) =>
            video.document_id === item.after &&
            video.observed_at >= item.received_at,
        ),
    );
    const complete =
      !!submission &&
      submission.run_id === run.run_id &&
      submission.session_id === run.session_id &&
      submission.plan_hash === run.plan_hash &&
      run.commissioning === true &&
      run.scene === "workflow-studio-flex" &&
      run.instrument === "flex" &&
      run.status === "completed" &&
      run.completed_steps === 4 &&
      run.total_steps === 4 &&
      run.snapshot?.run_id === run.run_id &&
      run.snapshot.plan_hash === run.plan_hash &&
      run.snapshot.status === "completed" &&
      run.snapshot.steps.length === 4 &&
      run.snapshot.steps.every((step) => step.status === "completed") &&
      run.snapshot.native_state?.studio?.observation_model ===
        "native-semantic" &&
      run.cleanup?.reset_verified === true;
    if (!complete)
      issues.push(
        `Run ${index + 1} is missing matching completion and reset receipts.`,
      );
    if (
      !videos.length ||
      !browser ||
      browser.run_id !== run.run_id ||
      browser.native_session_id !== binding.native_session_id ||
      browser.plan_hash !== run.plan_hash ||
      browser.source !== "browser-report" ||
      browser.frames_decoded <= 0
    )
      issues.push(
        `Run ${index + 1} is missing decoded current-relay video evidence.`,
      );
    if (index === 0 && !recovery)
      issues.push(
        "First-run reload and fresh video recovery are not verified.",
      );
    return {
      run_id: run.run_id,
      session_id: run.session_id,
      plan_hash: run.plan_hash,
      scene: run.scene,
      instrument: run.instrument,
      frames_decoded: Math.max(
        0,
        ...videos.map((video) => video.frames_decoded),
      ),
      relay_verified: videos.length > 0,
      refresh_frames_decoded: recovery
        ? Math.max(
            0,
            ...videos
              .filter((video) => video.document_id === recovery.after)
              .map((video) => video.frames_decoded),
          )
        : 0,
      completed_steps: run.completed_steps,
    };
  });
  if (
    new Set(server.runs.map(({ run }) => run.run_id)).size !== 2 ||
    new Set(server.runs.map(({ run }) => run.plan_hash)).size !== 2
  )
    issues.push("Two distinct runs and saved designs are required.");
  return {
    schema: "academy.studio-browser-commissioning/1",
    source: "authenticated-in-app-observations",
    status: issues.length ? "incomplete" : "completed",
    grant_id: server.grant_id,
    submission_posts: state.submissions.length,
    refresh_verified: (runs[0]?.refresh_frames_decoded ?? 0) > 0,
    browser_runs: runs,
    browser_receipts: receiptProof(state),
    server_report: publicReport(server),
    issues,
  };
}
