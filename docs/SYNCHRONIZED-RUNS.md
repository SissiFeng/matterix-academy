# Synchronized Academy and Matterix execution

Required behavior, agreed 2026-10-01: **Run experiment starts the student's saved workflow in Matterix/Isaac, and Academy displays progress and state reported by that same simulation run.** Showing a sequence of teaching steps or an unrelated 3D video does not meet this requirement.

## End-to-end flow

```mermaid
sequenceDiagram
  actor Student
  participant UI as Academy browser
  participant API as Academy API and run records
  participant Worker as Ubuntu outbound worker
  participant Gateway as Ubuntu gateway
  participant Sim as Matterix / Isaac runner
  Student->>UI: Run experiment
  UI->>API: Run the saved experiment revision
  API->>API: Persist owner, run ID and immutable plan
  Worker->>API: Claim immutable plan and obtain one start grant
  Worker->>Gateway: Journal intent, allocate lease and submit this plan once
  Gateway->>Sim: Start or reuse an isolated runtime; configure scene
  Gateway-->>Worker: Queued / loading (0 completed steps)
  Worker->>API: Publish initial snapshot
  Sim->>Sim: Execute the mapped actions in order
  loop While the run is active
    Sim-->>Gateway: Action outcomes and native observations
    Worker->>Gateway: Read the original run ID
    Gateway-->>Worker: Versioned cumulative progress snapshot
    Worker->>API: Publish validated cumulative snapshot
    API-->>UI: Current step, confirmed progress, native state and freshness
  end
  Sim-->>Gateway: Final outcome and observations
  Gateway-->>Worker: Completed / failed
  Worker->>API: Final report, then verified reset and release receipt
  API-->>UI: Result and learning record
```

Academy owns learner identity, the submitted plan and durable run records. Matterix owns execution and simulation state. The gateway maps approved plans and observations between them; it must not replace Matterix's outcomes with its own timer, teaching-model calculation or retry policy. Simulation startup may allocate an already-running, verified-clean instance; starting another heavy Isaac process on every button click is not required.

## The same workflow means the same inputs

The submitted plan includes action order, action volumes, source/destination wells, deck layout and initial liquid volumes. `RemoteRunRequest` binds the normalized `Experiment` to a `run_id` and SHA-256 `plan_hash`. Persist the exact request before any dispatch. Changing the saved experiment after submission cannot alter an in-flight run. A reset and retry require a fresh run ID after reset has been confirmed.

The hash uses `workflow_digest`: validate through the shared `Experiment` model, serialize its complete JSON-mode dump with sorted keys, compact separators and ASCII escaping, then hash the UTF-8 bytes. The gateway must use the same canonicalization rather than hash arbitrary incoming JSON text. The current allocation client still selects `flex-first-transfer-v1`; supporting other scenes or dilution plans requires explicit native capability qualification, not just accepting their request schema.

The Ubuntu adapter must resolve logical objects (`tips`, `stock`, `plate`, `waste`) and well IDs to the installed scene's versioned labware, transforms and supported actions. It must validate the complete plan before starting. An unsupported layout, volume, action or required observation produces an explicit preflight failure; never substitute a preset workflow or silently change the student's values. A digest binds content, not authorization or native compatibility.

The local Matterix entry point `scripts/run_workflow.py` uses its state machine and a simulation loop, and can repeat episodes or reset environments. It is a reference for integration, not a ready-made Academy service. An Academy run must have bounded, single-attempt semantics: environment termination or timeout must not reset and replay the student's transfers. Native pickup, transfer and discard outcomes must map back to the corresponding lesson step, including any internal motion substeps.

## Progress comes from execution

The proposed gateway endpoints are:

- `POST /v1/sessions/{session_id}/runs`: submit the full `RemoteRunRequest` once and receive a cumulative `RemoteRunSnapshot`.
- `GET /v1/sessions/{session_id}/runs/{run_id}`: recover the same run, including when its initial response was lost. This never starts a new run.

Snapshots carry session/run identity, plan hash, monotonic sequence, session revision, engine/asset versions, observation time, all step states and available native observations. A received or queued request contributes zero completed steps. A completed step must have a runtime confirmation timestamp and bound observation revision; the snapshot must include matching or newer native observation metadata. The client rejects identity mismatches, reordered steps, stale snapshots, changed reports under the same sequence, retracted confirmations and progress after a terminal outcome.

Consecutive completed steps have nondecreasing confirmation times and observation revisions; equality is allowed for batched observations. A native observation revision is immutable: a later message cannot report different volumes, tip state, time or tick under the same native revision.

`completed_steps / total_steps` expresses confirmed action progress, not estimated wall-clock progress. Display the current action separately because movement and aspiration can take different amounts of time. Run completion requires an explicit terminal status, not merely a percentage. A runtime confirmation reports what the simulator says it executed; it does not by itself prove scientific success, physical accuracy or measured transfer volume.

Liquid and tip fields come from native observations. Unavailable values are `null`, displayed as **Not observed**, rather than zero or synthetic predictions. Lesson expectations can be shown alongside them under a separate label. Observed outcomes and lesson success must remain distinguishable when the runtime does not expose all quantities needed by an assessment.

## Browser state, controls and video

Required student states include **Queued**, **Starting simulation**, **Running**, **Pause requested**, **Paused**, **Reconnecting**, **Completed**, **Failed** and **Outcome unknown**. A failed poll retains the last confirmed state with its timestamp and a stale/reconnecting indicator. It must never advance the timeline or change to synthetic results.

Start with periodic reads of the cumulative snapshot through the Academy API. SSE or WebSocket transport may replace polling later without changing state ownership or completion rules. The gateway maintains the sequence across reconnects; a restarted runtime that cannot recover the original run reports uncertainty instead of resetting its sequence and pretending to resume.

Pause is a request until the runner acknowledges its supported pause boundary. Reset is unavailable while a transfer's outcome remains unresolved. Closing or refreshing the browser must not control the remote simulation loop: the durable runner follows the configured lease policy, and reopening retrieves the original run. No automatic POST retry follows a timeout, disconnect or lost acknowledgement.

The 3D stream and structured state describe the **same session and run**. Frame metadata should include run identity and simulation time/tick so the UI can show video delay independently of state freshness. Perfect frame-by-frame equality across a network is not assumed. A disconnected or delayed stream gets its own indicator; video playback never confirms step completion. Authenticated media grants and the native frame/observation adapter remain to be implemented and qualified.

## Implemented versus pending

Implemented in Academy: typed workflow/native progress contracts, atomic durable queue/run/session records, separate machine API and authorizer, bounded worker leases, one start grant, journaled outbound worker, read-only recovery, validated reset receipts, and learner polling UI. [WORKER-CONTROL.md](WORKER-CONTROL.md) documents the authority, recovery and qualification boundaries. Fault tests use synthetic transports and native-looking fixtures.

Still pending: installed Ubuntu gateway endpoints, native scene/action/observation/reset adapter, authenticated media binding and live end-to-end qualification. The separate remote button remains disabled by the deployment flag until these pass. The existing student `Run experiment` continues to use the explicitly labeled teaching model; a capability response alone cannot enable native execution.

## Acceptance scenario

1. Submit a 100 µL lesson, observe startup and each native action, and show the same run in the UI and video.
2. Submit the 50 µL challenge with a new run ID and confirm that the runtime receives 50 µL, with the actual submitted layout and initial state.
3. Lose the submission response after execution begins; reconnect by the original run ID and prove only one transfer occurred.
4. Pause and refresh the browser; verify the acknowledged simulator state and saved Academy view agree.
5. Deliver an older snapshot and another session's response; neither may replace the current progress.
6. Stop or fault the simulation; Academy must show the failure/uncertainty, not advance to success. Missing native liquid observations remain visibly unavailable.
7. Confirm a complete reset of participating state before allowing another learner or attempt to start.

Passing contract tests is not passing these native acceptance scenarios.
