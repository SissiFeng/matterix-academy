# Outbound worker control plane

Implementation date: 2026-10-01. This implements AWS dispatch and the outbound worker protocol. The installed Ubuntu gateway, native runtime controls, reset-verification endpoint and GPU acceptance are separate deliverables. `remote_execution_enabled=false` remains the deployment default.

## Authority and storage

The learner API trusts only Cognito access-token claims supplied by the API Gateway JWT authorizer. Learner data remains scoped to `sub`. This release has no teacher cross-user access or enterprise tenant claims. Adding those requires server-managed membership data or an explicitly configured access-token trigger; tenant attributes must not be user-writable.

The dedicated worker HTTP API uses a zero-cache Lambda authorizer. Its high-entropy `worker-id.secret` credentials are hashed in the registry; the protected token exists only in the worker's systemd credential file. The authorizer binds `worker_id` and credential generation; every handler also checks revocation/expiry. Request bodies cannot select machine identity, qualification, role or tenant. Enrollment is an operator CLI action, not a public registration route. Machine tokens never authenticate the learner API.

The existing DynamoDB table contains learner records plus separate `system#runs`, `system#queue` and `system#workers` partitions. A transaction creates the immutable run, queue entry and session pointer while checking/incrementing the saved experiment version. `remote_active_run` blocks editing, reset and teaching execution until cleanup. A stable caller-generated `run_id` binds owner, session and submitted version; retrying the same submission retrieves the original run. A conflicting ID fails. The queue uses partition queries, not table scans.

## Runtime lifecycle

1. Worker claims one queued run. The transaction removes its queue entry and marks both run and worker busy. Repeating a claim after a lost response returns the same assignment.
2. Before any allocation or native mutation, the worker journals its run and intent IDs, then obtains the persisted `start` grant. A second grant ID is rejected. v1 never automatically requeues a claimed run, including a claim with no snapshot.
3. The worker allocates by a prewritten allocation ID, verifies the allocation-to-session binding, binds the actual native session/revision and submits the exact immutable plan. The journal precedes every native mutation; after a lost acknowledgement or restart, recovery only reads the original allocation/run/control/reset/release ID. Pending allocation/reset/release operations remain pending and are queried by their original operation ID. A missing lookup never authorizes another native POST.
4. Native reports must match the run, plan, bound native session, pinned engine/assets and ordered confirmation rules. Exact snapshot replays are acknowledged, including a terminal report whose response was lost. A pending control may be acknowledged by an otherwise identical paused snapshot.
5. Browser controls carry a command ID and expected run version. Pause/resume/cancel are requests until native acknowledgement. Native controls require their own qualification. Startup cancellation is rejected until startup resolves; queued cancellation needs no simulator call.
6. Worker heartbeats extend a 60-second lease up to a 30-minute deadline. Expired/revoked claims become `outcome_unknown`; the worker and session remain reserved. EventBridge checks every minute; mutation endpoints reject expiry immediately. No reported progress advances from a timer or a lost connection.
7. Known terminal runs reset through a journaled command, obtain native reset-verification evidence, release the native lease through a separate journaled command, then report cleanup. All object/liquid/tip/controller/stopped checks must pass. Failed or unresolvable cleanup quarantines the worker and leaves the learner session locked. An unknown execution requires operator reconciliation before reset. A missing journal also quarantines known terminal assignments without recreating mutation intent; the operator closeout below is required.

A single worker process owns its local SQLite journal through an OS file lock. Keep the journal across restarts; do not delete it to recover a stuck run. The gateway must independently implement durable allocation/run/command deduplication. Control-plane tests do not prove the gateway implements that requirement.

## Routes

Learners: `POST /api/runs`, `GET /api/runs/{id}`, `POST /api/runs/{id}/control`, `GET /api/sessions/{id}/remote-run`, `GET /api/runs/status`.

Machines: `GET /internal/workers/me`, `POST /internal/runs/claim`, `GET /internal/runs/{id}`, and `POST /internal/runs/{id}/{start,binding,heartbeat,snapshots,unknown,cleanup}`. There is no browser CORS or unauthenticated machine health route. Claim is a short request; idle workers back off to at most 20 seconds between empty claims and active runs return to a two-second interval.

The learner view shows the saved run identity, native confirmed progress, explicitly unobserved quantities, stale/reconnecting state and unresolved cleanup. It persists a submission ID before transmission and never substitutes teaching results or video for native evidence. Video/Three.js are not part of this first slice.

## Ubuntu handoff

Owner: the lab operator who controls the existing Matterix host. Required deliverable: a version-pinned gateway with all `MATTERIX-CONTRACT.md` acceptance records, including the additions below. This release does not install, reset or qualify the existing host.

Use a separate non-login `matterix-worker` service account. Install this repository's Python package beside, not inside, the Matterix/assets checkouts. Copy `ops/matterix-worker.service` and configure protected credential files. The gateway URL must use verified HTTPS. Do not put tokens in arguments, URLs, Git, frontend variables or logs.

Install the two existing credentials as root-owned files; the system manager supplies read-only copies to the service account through `LoadCredential`. The source directory is root-only. Substitute the operator's protected source paths; these commands do not generate or display credentials:

```sh
sudo install -d -o root -g root -m 0700 /etc/matterix-worker
sudo install -o root -g root -m 0600 /operator-protected-directory/lab-1.token /etc/matterix-worker/worker.token
sudo install -o root -g root -m 0600 /operator-protected-directory/gateway.token /etc/matterix-worker/gateway.token
```

Install `worker.env` in that directory with root ownership and mode `0600`; it contains only `ACADEMY_WORKER_API_URL` and `ACADEMY_GATEWAY_URL`, not token values. Do not change source-file ownership to `matterix-worker` or grant group/other access to make the service read them directly.

Enrollment (operator credentials; no token output):

```sh
AWS_PROFILE=pas-sdl0-dev AWS_DEFAULT_REGION=ca-central-1 \
  uv run python -m academy.worker_admin enroll \
  --expected-account-id 247893369214 --table matterix-academy-dev \
  --worker-id lab-1 --engine-version INSTALLED_COMMIT --asset-version INSTALLED_ASSETS \
  --credential-file /operator-protected-directory/lab-1.token
```

Enrollment creates an **unqualified, quarantined** worker. It durably publishes a complete mode-`0600` token before its atomic registration transaction. If the database fails or its acknowledgement is lost, preserve the credential file and retry the exact command; matching credentials recover the existing registration without issuing a new secret or extending its expiry. Never delete the file as a response to a database timeout. A different, expired or revoked identity is rejected.

The token expires after 90 days. Rotate by enrolling a new idle worker identity and revoking the old one; never change an active worker's identity mid-run. A transaction reserves a slot and inserts the worker together, enforcing a total registry bound of 100 records, including retired identities. The `system#registry/workers` counter is initialized automatically only for an empty registry. An older nonempty registry without that counter fails closed and requires a separate operator migration; do not manually reset the count to gain capacity.

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

Do not mark this example as evidence. After actual native verification, the operator runs `worker_admin qualify` with the same account/table/worker arguments and `--qualification-record PATH`. Enable the Terraform feature flag only after the evidence is reviewed. The record must list `scenes` explicitly (there is no default). A `flex-first-transfer` scene must also declare `capabilities.flex-first-transfer`: allowed slots per logical labware (`tips`, `stock`, `plate`, `waste`), wells, the qualified volume range, maximum starting stock and maximum action count. Learner submissions and claims are preflighted against these declarations (`native_plan.py`); a plan no scene supports exactly as saved is rejected with explicit issues, never adapted. The operator owns unresolved outcomes and failed cleanup; acceptance is a fresh clean scene for the next learner, not just a restarted service. No completion deadline can be set until host access and the installed gateway are supplied.

## Operator recovery after revocation, expiry or journal loss

The machine API continues rejecting revoked and expired credentials, including cleanup requests. Recovery uses `worker_admin reconcile` with the operator's AWS IAM credentials and an explicitly pinned account; it is not a machine or learner HTTP endpoint. The operator requires read/query and conditional transactional-write permissions on this application's records table. The application release role is not an operator recovery role.

1. Stop the worker process and prevent it from restarting. Revoke its credential using `worker_admin revoke` with the same account/table/worker arguments. Preserve its local journal and gateway operation records. The reaper marks any nonterminal assignment `outcome_unknown` without retrying it.
2. On the installed host, reconcile the original allocation/run and outstanding operation IDs. Obtain real native evidence that execution stopped, reset checks passed and the original native allocation was released. If a cloud binding was never saved, verify that no allocation remains on that worker before declaring `no_allocation`; uncertainty keeps the session locked. Do not infer these facts from a reboot, missing HTTP response or the teaching model.
3. Run `worker_admin inspect` with the same account/table/worker arguments to retrieve current run/worker versions, native session and runtime identity without exposing tokens or learner identity. Save a reconciliation JSON using those values and the actual report location. The following is a schema example, **not acceptance evidence**:

```json
{
  "reconciliation_id": "NEW-UUID-FOR-THIS-CLOSEOUT",
  "worker_id": "lab-1",
  "run_id": "ORIGINAL-RUN-UUID",
  "expected_run_version": 12,
  "expected_worker_version": 14,
  "native_session_id": "ORIGINAL-NATIVE-SESSION-UUID",
  "reset_command_id": "VERIFIED-RESET-COMMAND-UUID",
  "release_command_id": "VERIFIED-RELEASE-COMMAND-UUID",
  "engine_version": "INSTALLED_COMMIT",
  "asset_version": "INSTALLED_ASSETS",
  "evidence": "native",
  "report_uri": "operator-owned location of the actual recovery evidence",
  "reset_verified": true,
  "no_allocation": false,
  "checks": {
    "worker_stopped": true,
    "objects": true,
    "liquids": true,
    "tips": true,
    "controllers": true,
    "stopped": true,
    "released": true
  }
}
```

For an unbound run with verified absence of any allocation, use `no_allocation: true` and `null` for the three native session/reset/release IDs; the report must still establish every host cleanup check. A run with an existing cloud binding requires its exact native session and real reset/release command IDs.

```sh
AWS_PROFILE=pas-sdl0-dev AWS_DEFAULT_REGION=ca-central-1 \
  uv run python -m academy.worker_admin reconcile \
  --expected-account-id 247893369214 --table matterix-academy-dev \
  --worker-id lab-1 --reconciliation-record /operator-protected-directory/recovery.json
```

The closeout atomically records the operator ARN, evidence and versions, releases the learner session lock, and retires the old worker credential. It preserves the original execution outcome, including `outcome_unknown`; cleanup does not prove execution succeeded. The worker remains revoked, unqualified and quarantined. The internal audit record is not returned to learners. A lost acknowledgement is recovered by repeating the exact same receipt; different data under its reconciliation ID or stale versions are rejected. A fresh worker identity and qualification are required before another native run. No native reset or release is issued by this CLI.

## Evidence and limitations

SQLite/mocked DynamoDB tests cover conditional writes and rollback, ownership, credential revocation, immutable plans, duplicate/lost acknowledgements, native intent recovery, expiry quarantine and verified cleanup. Browser fixture tests cover stale views and read-only reconnection. All simulator-looking test reports are synthetic fixtures. Native Matterix, GPU behavior, authenticated media and classroom capacity require separate tests on the installed host.
