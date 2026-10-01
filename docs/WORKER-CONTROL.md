# Outbound worker control plane

Implementation date: 2026-10-01. This implements AWS dispatch and the outbound worker protocol. The installed Ubuntu gateway, native runtime controls, reset-verification endpoint and GPU acceptance are separate deliverables. `remote_execution_enabled=false` remains the deployment default.

## Authority and storage

The learner API trusts only Cognito access-token claims supplied by the API Gateway JWT authorizer. Learner data remains scoped to `sub`. This release has no teacher cross-user access or enterprise tenant claims. Adding those requires server-managed membership data or an explicitly configured access-token trigger; tenant attributes must not be user-writable.

The dedicated worker HTTP API uses a zero-cache Lambda authorizer. Its high-entropy `worker-id.secret` credentials are hashed in the registry; the protected token exists only in the worker's systemd credential file. The authorizer binds `worker_id` and credential generation; every handler also checks revocation/expiry. Request bodies cannot select machine identity, qualification, role or tenant. Enrollment is an operator CLI action, not a public registration route. Machine tokens never authenticate the learner API.

The existing DynamoDB table contains learner records plus separate `system#runs`, `system#queue` and `system#workers` partitions. A transaction creates the immutable run, queue entry and session pointer while checking/incrementing the saved experiment version. `remote_active_run` blocks editing, reset and teaching execution until cleanup. A stable caller-generated `run_id` binds owner, session and submitted version; retrying the same submission retrieves the original run. A conflicting ID fails. The queue uses partition queries, not table scans.

## Runtime lifecycle

1. Worker claims one queued run. The transaction removes its queue entry and marks both run and worker busy. Repeating a claim after a lost response returns the same assignment.
2. Before any allocation or native mutation, the worker journals its run and intent IDs, then obtains the persisted `start` grant. A second grant ID is rejected. v1 never automatically requeues a claimed run, including a claim with no snapshot.
3. The worker allocates by a prewritten allocation ID, binds the actual native session/revision and submits the exact immutable plan. The journal precedes every native mutation; after a lost acknowledgement or restart, recovery only reads the original allocation/run/control/reset/release ID. A missing lookup never authorizes another native POST.
4. Native reports must match the run, plan, bound native session, pinned engine/assets and ordered confirmation rules. Exact snapshot replays are acknowledged, including a terminal report whose response was lost. A pending control may be acknowledged by an otherwise identical paused snapshot.
5. Browser controls carry a command ID and expected run version. Pause/resume/cancel are requests until native acknowledgement. Native controls require their own qualification. Startup cancellation is rejected until startup resolves; queued cancellation needs no simulator call.
6. Worker heartbeats extend a 60-second lease up to a 30-minute deadline. Expired/revoked claims become `outcome_unknown`; the worker and session remain reserved. EventBridge checks every minute; mutation endpoints reject expiry immediately. No reported progress advances from a timer or a lost connection.
7. Known terminal runs reset through a journaled command, obtain native reset-verification evidence, release the native lease through a separate journaled command, then report cleanup. All object/liquid/tip/controller/stopped checks must pass. Failed or unresolved cleanup quarantines the worker and leaves the learner session locked. An unknown execution requires operator reconciliation before reset.

A single worker process owns its local SQLite journal through an OS file lock. Keep the journal across restarts; do not delete it to recover a stuck run. The gateway must independently implement durable allocation/run/command deduplication. Control-plane tests do not prove the gateway implements that requirement.

## Routes

Learners: `POST /api/runs`, `GET /api/runs/{id}`, `POST /api/runs/{id}/control`, `GET /api/sessions/{id}/remote-run`, `GET /api/runs/status`.

Machines: `GET /internal/workers/me`, `POST /internal/runs/claim`, `GET /internal/runs/{id}`, and `POST /internal/runs/{id}/{start,binding,heartbeat,snapshots,unknown,cleanup}`. There is no browser CORS or unauthenticated machine health route. Claim is a short request; idle workers poll with backoff.

The learner view shows the saved run identity, native confirmed progress, explicitly unobserved quantities, stale/reconnecting state and unresolved cleanup. It persists a submission ID before transmission and never substitutes teaching results or video for native evidence. Video/Three.js are not part of this first slice.

## Ubuntu handoff

Owner: the lab operator who controls the existing Matterix host. Required deliverable: a version-pinned gateway with all `MATTERIX-CONTRACT.md` acceptance records, including the additions below. This release does not install, reset or qualify the existing host.

Use a separate non-login `matterix-worker` service account. Install this repository's Python package beside, not inside, the Matterix/assets checkouts. Copy `ops/matterix-worker.service` and configure protected credential files. The gateway URL must use verified HTTPS. Do not put tokens in arguments, URLs, Git, frontend variables or logs.

Enrollment (operator credentials; no token output):

```sh
AWS_PROFILE=pas-sdl0-dev AWS_DEFAULT_REGION=ca-central-1 \
  uv run python -m academy.worker_admin enroll \
  --expected-account-id 247893369214 --table matterix-academy-dev \
  --worker-id lab-1 --engine-version INSTALLED_COMMIT --asset-version INSTALLED_ASSETS \
  --credential-file /operator-protected-directory/lab-1.token
```

Enrollment creates an **unqualified, quarantined** worker. The token expires after 90 days. Rotate by enrolling a new idle worker identity and revoking the old one; never change an active worker's identity mid-run. Registry size is bounded to 100 workers in this release.

The gateway must additionally provide:

- `POST /v1/sessions/{session}/runs/{run}/controls/{command_id}` with `action` and `expected_revision`; `GET` of the same URI recovers its original cumulative snapshot. Cancellation returns a stopped/paused or already-terminal report. Both paths must preserve run/plan identity.
- After `reset` completes, `GET /v1/sessions/{session}/reset-verification/{command_id}` returns `command_id`, `native_session_id`, pinned engine/asset versions, `reset_verified`, and boolean checks for `objects`, `liquids`, `tips`, `controllers`, `stopped`. These must be measured from the installed native scene, never generated from the intended reset command.
- Release lookup records survive release so a lost release response remains recoverable.

Qualification record schema:

```json
{
  "evidence": "native",
  "worker_id": "lab-1",
  "engine_version": "INSTALLED_COMMIT",
  "asset_version": "INSTALLED_ASSETS",
  "report_uri": "operator-owned location of the actual acceptance evidence",
  "controls": [],
  "checks": {
    "session_isolation": true,
    "plan_binding": true,
    "at_most_once": true,
    "native_observations": true,
    "reset_verification": true,
    "release": true,
    "restart_recovery": true,
    "no_hardware": true
  }
}
```

Do not mark this example as evidence. After actual native verification, the operator runs `worker_admin qualify` with the same account/table/worker arguments and `--qualification-record PATH`. Enable the Terraform feature flag only after the evidence is reviewed. The operator owns unresolved outcomes and failed cleanup; acceptance is a fresh clean scene for the next learner, not just a restarted service. No completion deadline can be set until host access and the installed gateway are supplied.

## Evidence and limitations

SQLite/mocked DynamoDB tests cover conditional writes and rollback, ownership, credential revocation, immutable plans, duplicate/lost acknowledgements, native intent recovery, expiry quarantine and verified cleanup. Browser fixture tests cover stale views and read-only reconnection. All simulator-looking test reports are synthetic fixtures. Native Matterix, GPU behavior, authenticated media and classroom capacity require separate tests on the installed host.
