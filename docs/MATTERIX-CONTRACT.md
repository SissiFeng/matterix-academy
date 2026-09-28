# Ubuntu integration contract — proposed v1

This is a **new gateway contract**, not a claim that these endpoints exist in the current Matterix repository. No commands in this release are sent to Ubuntu. `gateway.py` implements only read-only capability qualification; the student platform deliberately reports Matterix unavailable.

The gateway runs next to Matterix on a managed Ubuntu GPU host. The operator supplies its HTTPS base URL and service credential through deployment configuration/Secrets Manager. A student cannot supply gateway URLs, executable code, shell commands, asset paths or credentials. Streaming and service access need authenticated, expiring session grants; students receive no Linux accounts.

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

## Session endpoints to implement in the next slice

| Endpoint | Semantics |
|---|---|
| `POST /v1/sessions` | Allocate an isolated simulation lease from an operator-controlled scene catalog; include caller-generated allocation idempotency key. |
| `GET /v1/sessions/{id}` | Return authoritative state, revision, engine/asset versions, lease expiry and observation timestamps. |
| `POST /v1/sessions/{id}/commands` | Submit an allowlisted action with expected revision and command ID; return accepted operation ID. |
| `GET /v1/sessions/{id}/operations/{operation_id}` | Resolve accepted/completed/failed/unknown without replaying an uncertain command. |
| `POST /v1/sessions/{id}/reset` | Reset physics, liquid, consumables and controller state as one acknowledged operation. |
| `DELETE /v1/sessions/{id}` | Release only that session's resources. |

A command timeout produces `unknown`, followed by operation-status reconciliation. It must never produce an automatic duplicate transfer. Do not forward credentials to browser-controlled destinations or another gateway on redirect. Issue media grants independently of the service credential; do not embed a raw unauthenticated Isaac editor.

## Required acceptance evidence

1. Two learner sessions cannot inspect, move, reset or release one another's scene.
2. A valid Flex sequence reports native observations with a matching engine/asset version.
3. No-tip, capacity, empty-source and failure paths return explicit outcomes.
4. Repeated command IDs do not repeat execution; stale revisions are rejected.
5. Reset restores all participating state, including attachments and liquids.
6. Lease expiry and gateway restart do not leave abandoned sessions consuming resources indefinitely.
7. Streaming access is session-scoped and expiring; neither OS nor general script-editor access is exposed.
8. No hardware connector or physical device command path is reachable.

The Academy API can remain on AWS while the GPU host is on-premises. The HTTPS command path and WebRTC media path are separate network concerns; CloudFront/API Gateway do not proxy arbitrary WebRTC UDP traffic. Choose private connectivity and a secured media gateway during deployment, then test the actual installed Isaac version.
