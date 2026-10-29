# Sim–Real connector delivery and execution

Status: local implementation; not deployed or hardware-qualified. See [SETUP.md](SETUP.md) for the operator flow and acceptance boundaries.

## Scope and boundaries

An English Connect an instrument page is available inside Sim–Real. A separately installed
local companion makes outbound authenticated connections to Academy. Robot SSH
keys, network addresses and calibration stay on the lab computer. A browser does
not silently install software or grant physical motion authority.

The connector runtime stays in its independent AC repository and runs on the
robot. Artifact intake pins source, build provenance, SHA256 and compatibility;
candidates are never installable until explicitly approved. Updates never change
an active installation or run. No AWS infrastructure or physical commands are
created/executed during local feature development.

Academy owns user identity, pairing, per-device locking and workflow authorization.
The existing independent bridge informs mapping/receipt/recovery semantics; its
local dirty 0.8 code is not copied or published. Native DT and hardware remain
separate evidence tracks. Teaching success cannot unlock hardware.

A constrained compiler produces an Opentrons Protocol Engine protocol from
the saved Studio plan and an operator-qualified local labware/pipette profile.
SiLA performs identity/capability checks; Protocol Engine executes whole protocols.
This is not advertised as a SiLA whole-workflow command. Unsupported instruments,
firmware, labware, actions and unqualified profiles fail closed. No raw motor
coordinates or arbitrary user code are accepted from the browser.

## Offline mock SiLA2 connector

Learners can run a saved Studio workflow without an instrument, companion, GPU or
network. **Connect an instrument → Try an offline connector** uses an in-process
adapter (`academy/mock_connector.py`, `/api/connector-mock`). Its runs are
owner-scoped and versioned, like other session mutations. Results are labelled
synthetic and never feed native, hardware or receipt gates.

Connector developers can run the same model behind actual SiLA2 on loopback:

```bash
cd ops/mock-sila && uv run academy-mock-sila --port 50052
```

It exposes `SiLAService`, a `SimulationController` that refuses Real Mode, and
`MockWorkflowRunner.RunWorkflow` (Studio experiment JSON in, synthetic result
JSON out). It has no TLS, binds only to loopback and has no discovery or cloud
connection. `uv run pytest` in that directory exercises it over gRPC.

## Implementation ownership

- Backend: connection records, atomic single-use pairing, dedicated machine token,
  native-evidence/plan-bound run gating, receipts, revocation and tests.
- Companion: outbound client, protected local state, verified package staging,
  read-only probe, constrained protocol compiler/executor and fault tests.
- Frontend: connection/setup page, Sim–Real and Studio entry links, English status,
  explicit motion confirmation, refresh recovery and browser journeys.
- Integration: artifact catalog/promotion/S3 sync, build wiring, infrastructure
  configuration, documentation and independent full validation.

## Acceptance

Lambda packaging, verify.sh and all browser journeys are required before release. Test both stores,
owner isolation, pairing replay/expiry/concurrency, credential revocation, stale
versions, changed plans, missing/mismatched native results, unsupported package or
profile, duplicate dispatch, timeout/crash unknown state and immutable receipts.
Exercise a local Protocol Engine HTTP fixture through the real companion client;
label it software-only evidence. Review rendered desktop/mobile UI. Live Cognito,
S3 publication, real Matterix and supervised physical execution require separate
observed evidence before any readiness claim.
