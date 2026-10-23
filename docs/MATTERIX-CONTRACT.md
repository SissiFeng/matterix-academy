# Ubuntu integration contract — proposed v1

This is a **new HTTPS gateway contract**, not a claim that these endpoints exist in the current Matterix repository. The typed client in `gateway.py` implements capability qualification, allocation, snapshot, command, reconciliation, reset and release requests. The outbound worker uses its mutation methods behind durable Academy dispatch records. These methods are verified with synthetic HTTP fixtures; native server acceptance remains pending. The implemented local native adapter described below is a separate integration route. General student access remains unavailable until its scene is qualified and enabled.

The gateway runs next to Matterix on a managed Ubuntu GPU host. The operator supplies its HTTPS base URL and service credential through protected worker configuration and systemd credentials. A student cannot supply gateway URLs, executable code, shell commands, asset paths or credentials. Streaming and service access need authenticated, expiring session grants; students receive no Linux accounts.

The required student execution flow is specified in [SYNCHRONIZED-RUNS.md](SYNCHRONIZED-RUNS.md): submitting the saved workflow to Matterix and reflecting that same run's confirmed progress and native observations. `remote_run.py` and the client support the proposed whole-workflow request/snapshot contract. Durable Academy orchestration and student remote routes are implemented but disabled by default; see [WORKER-CONTROL.md](WORKER-CONTROL.md) for qualification, run controls and reset-verification extensions. The existing teaching runner is separate.

## Implemented local native adapter

The outbound worker can use `native_runner.py` and its supervised local process
instead of an inbound HTTPS gateway. This path implements fixed `flex-mixing` and
saved-plan `workflow-studio-flex`. Studio validates the complete immutable plan
against supported geometry, amounts, actions and pinned assets before allocation;
the runtime imports the independent internal Matterix and assets repositories.
It does not substitute the mixing recipe for a learner design. OT-2 is unavailable
in the approved Flex image; its reviewed asset profile and adapter remain pending.

Studio reports exact labware slots, native action progress, observed tip/pipette
state and finite container/waste accounting driven by native pipette storage.
These are **native-semantic** observations, not fluid, chemistry or hardware
validation. The API checks each confirmed plan prefix and the final exact end
state. An unknown dispatch is recovered by its original identity without replay.
Reset must restore objects, liquids, tips and controllers, and release must prove
the runtime processes stopped before another attempt can start.

KVS media grants and frame delivery bind to the same session/run/hash. General
learner access requires scene-specific native workflow and media evidence, worker
qualification and the global execution gate. A bounded commissioning grant may
authorize exactly two ordered plans for one subject and worker while that gate
stays off; it does not qualify the worker or enable general access.
See [Studio native acceptance](STUDIO-NATIVE-ACCEPTANCE.md). Real GPU/browser
acceptance remains pending. The isolated image probe checks native execution,
nonblack frames and reset; it cannot establish Cognito or WebRTC browser acceptance.

## Qualification endpoint implemented by the client

`GET /v1/capabilities`, authenticated with a service Bearer credential:

```json
{
  "contract_version": "1",
  "engine": "matterix",
  "simulation_only": true,
  "supports_isolated_sessions": true,
  "actions": ["pickup", "aspirate", "dispense", "drop"]
}
```

The client rejects redirects, unknown contract versions, non-Matterix evidence, hardware-enabled backends, missing session isolation and malformed responses. Capability acceptance alone is not sufficient to enable student access.

## Session endpoints implemented by the client; Ubuntu server implementation pending

| Endpoint | Semantics |
|---|---|
| `POST /v1/sessions` | Allocate an isolated simulation lease from an operator-controlled scene catalog; include caller-generated allocation idempotency key. |
| `GET /v1/allocations/{allocation_id}` | Recover the allocation result using an ID known before sending the request. Return allocation ID, pending/allocated/failed/unknown status, and session ID when allocated. |
| `GET /v1/sessions/{id}` | Return authoritative state, revision, engine/asset versions, lease expiry and observation timestamps. |
| `POST /v1/sessions/{id}/runs` | Submit the complete immutable experiment with original run ID, plan hash and expected revision. A receipt does not confirm any steps. |
| `GET /v1/sessions/{id}/runs/{run_id}` | Recover cumulative native progress for that exact workflow without re-executing it. |
| `POST /v1/sessions/{id}/commands` | Submit an allowlisted action with expected revision and command ID; return accepted operation ID. |
| `GET /v1/sessions/{id}/commands/{command_id}` | Recover a command/reset/release result when its acknowledgement, including the operation ID, was lost. |
| `GET /v1/sessions/{id}/operations/{operation_id}` | Resolve accepted/completed/failed/unknown without replaying an uncertain command. |
| `POST /v1/sessions/{id}/reset` | Reset physics, liquid, consumables and controller state as one acknowledged operation. |
| `DELETE /v1/sessions/{id}` | Release only that session's resources. |

A command timeout produces `unknown`, followed by operation-status reconciliation. It must never produce an automatic duplicate transfer. Do not forward credentials to browser-controlled destinations or another gateway on redirect. Issue media grants independently of the service credential; do not embed a raw unauthenticated Isaac editor.

The HTTPS allocation request uses `{allocation_id, scene_id: "flex-first-transfer-v1"}`. Scene IDs are an operator-controlled catalog, never asset paths supplied by students. Session snapshot responses require `id`, positive `revision`, `status`, `engine: "matterix"`, `simulation_only: true`, nonempty `engine_version`/`asset_version`, and timezone-aware `lease_expires_at`/`observed_at`. Whole-workflow snapshots separately carry typed native observations in `RemoteRunSnapshot`; an HTTPS server must implement and qualify that contract rather than infer execution from session metadata. The local adapter's supported scene catalog does not expand this HTTPS client's allocation catalog.

Every operation response includes the original `command_id`, an `operation_id`, and a status from `accepted/running/completed/failed/unknown`. Reset and release requests also carry unique caller-generated `command_id` and `expected_revision`. The gateway must durably register IDs before execution, associate them with the session and exact payload, and retain lookup records after release. A repeated ID must not execute twice; the same ID with a different payload is rejected. A lookup returning no record does not by itself prove the command never ran. Unknown outcomes remain blocked for reconciliation or operator recovery, with no automatic replay.

The client checks response identities, rejects redirects, does not retry mutations, and classifies network failures, 5xx responses and malformed successful mutation responses as unknown. This behavior is verified using mock transport, not a native Matterix server.

For a whole workflow, the gateway must durably bind `run_id` to the owning session and exact plan before dispatch. Reusing an ID with a different plan fails; looking up a missing run never authorizes automatic resubmission. Apply the command idempotency and retention rules above to run IDs as well. A whole-workflow runner and individual command submission must not execute concurrently in the same session.

## Required acceptance evidence

1. Two learner sessions cannot inspect, move, reset or release one another's scene.
2. A valid Flex sequence reports native observations with a matching engine/asset version.
3. No-tip, capacity, empty-source and failure paths return explicit outcomes.
4. Repeated command IDs do not repeat execution; stale revisions are rejected.
5. Reset restores all participating state, including attachments and liquids.
6. Lease expiry and gateway restart do not leave abandoned sessions consuming resources indefinitely.
7. Streaming access is session-scoped and expiring; neither OS nor general script-editor access is exposed.
8. No hardware connector or physical device command path is reachable.

For Studio, retain the exact two approved designs, source/image fingerprint,
run-bound native plans and observations, real renderer/browser frame evidence,
refresh recovery and both reset/release receipts described in
[STUDIO-NATIVE-ACCEPTANCE.md](STUDIO-NATIVE-ACCEPTANCE.md). Evidence evaluation and
local probe success do not themselves qualify a worker.

The Academy API can remain on AWS while the GPU host is on-premises. The HTTPS command path and WebRTC media path are separate network concerns; CloudFront/API Gateway do not proxy arbitrary WebRTC UDP traffic. The outbound worker reaches AWS through HTTPS; Lambda does not dial the Ubuntu gateway. Qualify the authenticated KVS media path against the actual installed Isaac renderer and learner browser before enabling general native access.
