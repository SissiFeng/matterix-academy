# Workflow Studio native acceptance

Status: implementation and synthetic contract tests are available; this document does
not record a completed GPU or real-account browser acceptance. The user resumed real
DT delivery on 2026-10-26 under the existing single-host resource authorization;
separate learner registration/two-account acceptance remains outstanding.
No AWS resource is created by the preparation steps below. Consult
[STATUS.md](STATUS.md), [GPU-CAPACITY-TRIAL.md](GPU-CAPACITY-TRIAL.md) and the reviewed
deployment inventory before a live run in the authorized development account.

The acceptance target is a saved Workflow Studio design in the English Onboarding
browser → the nominated internal Matterix worker → the exact Flex layout and actions
in Isaac → live video → refresh recovery → verified native reset → a second, changed
design. The teaching model continues to produce only synthetic learning results.

## Runtime and evidence boundary

Use the source and installed-runtime fingerprint in [COMMISSIONING.md](COMMISSIONING.md)
and [GPU-IMAGE-BUILD.md](GPU-IMAGE-BUILD.md): internal Matterix
`18a96b78ee989fbf4e480e9db6a588c148c6adbe`, internal assets
`c57f12a04079a5f99405e1fcb818a3b7ccc52e5b`, Isaac Lab `3.0.0b2.post1`, Isaac Sim
`6.0.1.0`, Python 3.12, and the exact reviewed GPU image dependencies. A new Academy
build must include the Studio adapter; an older 0.2.0 artifact with only the mixing
adapter cannot execute this acceptance. Retain the exact Academy commit, release
artifact checksums, AMI ID and installed package inventory with the evidence.

The current native scene is `workflow-studio-flex`, geometry version
`academy-flex-studio-v1`. Its supported movable slots are A1, A2, B1, B2, B3, C1, C2,
C3, D1 and D2. A3 is occupied by the approved CAD's rear trash geometry; D3 is the
fixed logical waste receptacle. Slot origins are
`(-0.2238 + 0.165*(column-1), 0.08544 + 0.107*index_in_DCBA(row), 0.1405)` metres;
the saved labware slots determine native origins and every action target. These
coordinates describe a versioned simulation scene, not measured hardware calibration.

The native adapter supports stock and plate wells A1–A3, 1–300 µL per liquid action,
300 µL pipette capacity, 1500 µL per container, up to 64 saved actions and 64 fresh
tips. It uses the right native pipette and approved 1000 µL tip geometry with the
lower 300 µL workflow limit. An unreachable target or unsupported plan fails before
motion. OT-2 remains unavailable in this reviewed Flex image: a separate OT-2
asset, deck mapping and qualification are required. The adapter never substitutes
a Flex robot, mixing recipe or teaching result for an OT-2 or unsupported design.

Volumes are **native-semantic observations**: finite container bookkeeping follows
the changes observed in Matterix's pipette storage during native simulation. Native
snapshots include instrument, scene, exact labware placements, action progress,
pipette volume, tip attachment, stock/A1/A2/A3 volumes and waste volume. Successful
accounting and rendered motion do not validate fluid dynamics, chemistry, calibrated
pipetting or physical hardware. The native local probe also does not establish
browser login, WebRTC relay or end-to-end browser acceptance.

## Operator approval of exactly two designs

Keep `ACADEMY_REMOTE_ENABLED=false`. Enroll one idle worker with the pinned sources;
it remains quarantined and unqualified. A Studio commissioning request retains the
existing fields `grant_id`, exact JWT `subject`, `worker_id`, `engine_version`,
`asset_version`, `duration_seconds` and `max_runs`, and adds:

```text
studio:
  scene: workflow-studio-flex
  instrument: flex
  capability: the reviewed native_studio_runtime.flex_capability() declaration
  plans:
    - experiment: complete normalized first Experiment
      plan_hash: workflow_digest(first Experiment)
    - experiment: complete normalized second Experiment
      plan_hash: workflow_digest(second Experiment)
```

Use `max_runs: 2` and a duration of 300–3600 seconds. `experiment` includes its title,
course ID, instrument, transfer-volume field, starting amounts, every labware slot
and every ordered action. A hash of only the transfer amount is insufficient.
Do not remove default fields from one copy or rename the design after approval.
`CommissioningRequest.model_validate_json(...)` validates hashes, source pins,
scene/instrument agreement and both plans against the declared capability.

For this acceptance, prepare these two designs in order:

| Field | First run | Second run |
|---|---|---|
| Course / instrument | `workflow-sandbox` / `flex` | Same |
| Initial stock | 1000 µL | 1000 µL, freshly reset |
| Initial A1/A2/A3 | 0 µL each | 0 µL each |
| Tips / stock / plate / waste slots | B1 / D1 / D2 / D3 | C1 / D1 / D2 / D3 |
| Actions | Pick up; aspirate stock 100 µL; dispense A1 100 µL; drop | Pick up; aspirate stock 50 µL; dispense A1 50 µL; drop |
| Expected terminal stock / A1 | 900 / 100 µL | 950 / 50 µL |
| Expected terminal pipette / waste | 0 / 0 µL, no attached tip | Same |

The evaluator also accepts another supported movable-slot change, but it requires
the 100 → 50 µL transfers, empty initial destination wells, the same initial stock
amount and a changed placement. It verifies the exact operator-approved plan for
each run; it does not infer a workflow from the expected final volume.

Keep the approval JSON outside the repository with restrictive permissions. Obtain
the subject through the existing authenticated operator workflow; never copy a
password, JWT or worker token into the request. A capability declaration on this
grant permits only these exact plans on this worker. It neither modifies enrolled
worker capabilities nor constitutes qualification.

After the host passes the read-only runtime inventory, this command is an explicit
administrative write to the existing deployment:

```sh
uv run python -m academy.commissioning authorize \
  --expected-account-id REVIEWED_ACCOUNT --table EXISTING_TABLE \
  --request /protected/studio-commissioning-request.json \
  --runtime-report /protected/runtime.json
```

No such write or live run is required to prepare/test this implementation. An active
grant is limited to one subject, one worker, source pins, exact scene, exact ordered
plans and two submissions. A failed or unknown run consumes its submission; there is
no automatic retry that creates another run. Reusing the same grant ID never extends
time or quota. Unresolved previous runs block a replacement grant. Global execution
and worker qualification remain unchanged.

## Browser run and recovery checks

Run the headed Studio acceptance harness only after live execution authorization and
the nominated user's login are available. The fixed-mixing harness in
[COMMISSIONING.md](COMMISSIONING.md) covers a different scene.

```sh
cd app/frontend
ACADEMY_COMMISSIONING_URL=https://REVIEWED_ONBOARDING_ORIGIN \
ACADEMY_COMMISSIONING_OUTPUT=/protected/studio-browser \
npm run commissioning:studio -- --confirm-live \
  --request /protected/studio-commissioning-request.json
```

The harness opens an ephemeral headed browser for manual Cognito login as the
already onboarded approved subject. It requires an unused matching grant, saves
each exact approved design through the authenticated session API, and launches
native execution through the Studio UI. It does not reuse a token from an operator
shell. This command is prepared, not executed as part of local development. Offline
harness contract tests use `npm run test:studio-commissioning` and create no resources.

1. Confirm the reviewed Onboarding release, matching worker/image pins and active
   subject-scoped grant. Save the first exact approved design. Read-only native
   preflight must return that session version, plan hash, Flex scene and a ready
   result. Another user, another instrument, a changed title/amount/slot or the second
   plan submitted first must remain unavailable under this grant.
2. Start native simulation through the Studio browser control. Record the saved
   session, run, plan hash and bound native session. Require actual decoded video
   frames from the current connection and relay-only ICE. Inspect the Flex robot,
   the approved first layout and the action/volume progression in the rendered view.
3. Refresh while the first run is active. Recover the same original run and native
   session through fresh authenticated reads, with nondecreasing confirmed progress.
   There must still be exactly one run submission, one native allocation and no
   replayed action caused by reload or polling. Reconnect video to that same run.
4. Require four observed completed steps, native-semantic volumes 900/100/0/0 µL,
   no held tip or pipette residue, and reset/release receipts proving objects,
   liquids, tips, controllers and both runtime processes stopped. A terminal label
   without verified cleanup is insufficient. Unknown outcomes require operator
   reconciliation, never an automatic second submission.
5. After cleanup releases the session lock, save/reset to the second exact approved
   design. Move tips B1 → C1 and change both transfer actions to 50 µL. Submit once
   through the browser. Require a new run/native session/hash, fresh relay video,
   the moved tip rack and final native-semantic volumes 950/50/0/0 µL. Require verified
   cleanup again. Across both runs there must be exactly two submission POSTs.
6. Retain screenshots and inspect rendered scene identity for both runs. Collect
   the authenticated `/api/commissioning/report`, runtime fingerprint and native
   artifact directories. Confirm the worker remains unqualified and global remote
   execution remains disabled. Do not label this as course credit or a synthetic
   teaching assessment.

## Correlating evidence

For each run retain `manifest.json`, `snapshot.json`, `studio-plan.json`,
`frame-proof.json`, `reset-proof.json`, `released.json`, `release-command.json` and
the native logs. `studio-plan.json` binds the run, native session, plan hash, source
pins, scene version, exact native origins and every ordered native target.
`frame-proof.json` binds nonblack renderer frames and simulation ticks to those IDs;
the browser report independently records decoded frames and relay connection checks.

```sh
uv run python -m academy.commissioning_evidence \
  --runtime-report /protected/runtime.json \
  --browser-report /protected/studio-browser/browser-report.json \
  --commissioning-request /protected/studio-commissioning-request.json \
  --runs-root /protected/native-runs \
  --output /protected/studio-acceptance.json
```

Studio evidence requires the separate operator-approved request. The server report's
grant ID, both ordered normalized plans, geometry, pins, observations, renderer and
browser receipts, refresh check and both reset/release receipts must match. Supplying
Studio artifacts to the older fixed-mixing invocation fails closed. Existing mixing
grants and their evidence format remain supported when `studio` is absent.

Exit 0 means the supplied artifacts are consistent; it does not establish their
provenance or qualify a worker. Independently review image identity, actual video,
isolation and interruption/recovery under [WORKER-CONTROL.md](WORKER-CONTROL.md) and
[MATTERIX-CONTRACT.md](MATTERIX-CONTRACT.md) before separately recording qualification
or enabling general learner access. Protect raw browser profiles, credentials,
signed media URLs and native claim journals; publish only sanitized evidence.

The scoped backend tests cover old mixing compatibility, approval validation,
SQLite/DynamoDB atomic reservation, wrong owner/worker/order/hash rejection,
disabled-global-gate preflight → queue → claim → media → cleanup → second run,
unchanged quarantine, and missing/tampered evidence. These are deliberately synthetic
fixtures. Only a completed run of the live procedure can establish browser-to-GPU
acceptance.
