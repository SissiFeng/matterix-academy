# Workcell onboarding and evidence workspace

The workspace opens on **Overview**, followed by **Onboard**, **Twin**, **Sim → Real** and **Runs**. Learning lab, discovery, workflow browsing, connector learning and native simulation remain available under Learn & Explore. Product copy remains English.

## What users can do

1. Register an Opentrons Flex by name and workcell. This is a manual declaration, not network discovery.
2. Select a planned connection: Native API, PyLabRobot, SiLA 2 connector or custom adapter. None of these choices sends network requests to an instrument or installs an adapter.
3. Declare intended capabilities. The teaching model covers tip pickup, aspiration, dispensing and tip disposal. Mixing, labware movement and imaging declarations are retained but not evaluated by this model.
4. Create a paired teaching twin. This atomically creates a persistent serial-dilution teaching session and attaches its identifier to the device. The existing experiment editor and runner operate on that exact session.
5. Review teaching capability coverage, saved trial outcomes and the missing physical evidence. The wizard saves each completed step and resumes from its saved state.

**Twin** shows the current saved teaching layout, volumes, tip state and event timeline. Physical values are unknown. The page makes no state synchronization or numerical difference claim. **Sim → Real** separates synthetic teaching checks from seven physical evidence gaps: connectivity, capabilities, geometry/reachability, resources, calibration, state consistency and physical execution. It reports evidence gaps rather than an invented readiness percentage. The physical execution button is always disabled.

**Runs** aligns the current teaching attempt's action sequence with its saved success/failure events. The physical column is unrecorded. Timing and state deviation remain not comparable. Prior attempts have summaries only, because the existing teaching store does not retain their full step traces or durations. Native simulation records retain their existing separate Simulation lab interface.

## Persistence and authority

- `GET /api/devices` lists the authenticated owner's first 100 device records with derived teaching checks. The list and all details use the existing identity dependency, including the trusted API Gateway authorizer context in AWS.
- `GET /api/devices/{id}` returns one owner-scoped record and its bound teaching session, if any.
- `PUT /api/devices/{id}` saves a bounded declaration with `expected_version` (zero for a new record). It rejects stale writes, duplicate capabilities, invalid progress, client-supplied owner, host, twin binding and readiness fields.
- `POST /api/devices/{id}/twin` requires the saved record's version and complete declarations. A conditional transaction writes both the device and new session, so two submissions cannot create two twins.
- Binding and physical-readiness fields are server-owned. Physical state is always absent in this release. Declaration changes cannot promote teaching evidence to hardware acceptance.
- Teaching checks are derived from the bound session on read. Resetting the trial invalidates its current passing result. Changing declarations recomputes capability coverage. Reading a check does not execute a teaching step.
- A lost mutation response triggers a read of the original device identifier. It does not replay the mutation. If reconciliation is unavailable, editing stays blocked until refresh resolves it. Conflicts reload the winning record and display a notice.
- Unsaved edits are guarded on navigation and page close; later wizard steps cannot bypass saving edits. Device and run links survive refresh and hash navigation.

## Acceptance boundary

This change is local product and application work. It does not add infrastructure, choose an AWS account, deploy the application, connect a physical instrument, qualify Ubuntu/Isaac, or enable real execution. The existing Matterix and assets repositories remain independent. A teaching trial is synthetic evidence only.

Run `bash scripts/build-lambda.sh`, `bash scripts/verify.sh`, and the frontend Playwright journeys. If a developer's cached Terraform directory points at a remote state backend, use an empty temporary `TF_DATA_DIR` for the verification script; backend-disabled initialization and validation should not require selecting an AWS account.
