# Status

Single source for current project status. Student trial source updated 2026-10-26
in [PR #10](https://github.com/SissiFeng/matterix-academy/pull/10); the
[live release record](https://d2m3yolcjdy6d2.cloudfront.net/version.json) identifies
the actual AWS application commit. Infrastructure observations below remain dated
2026-10-23 unless their linked evidence says otherwise. Dated evidence lives in
[VALIDATION.md](VALIDATION.md) and [DEPLOYMENT-2026-10-01.md](DEPLOYMENT-2026-10-01.md).
See the [student trial guide](STUDENT-TRIAL.md) for all feature entry points.

Legend: **Verified** = observed in a real environment. **Implemented** = code and automated tests exist; no real-environment evidence. **Blocked** = waiting on something outside this repository.

## Learner application

| Area | State | Notes |
|---|---|---|
| Teaching-model lessons (first transfer, dilution sandbox) | Verified locally | Synthetic by design; never labeled as Isaac or physical |
| Discovery studio, workflow marketplace, connector explorer | Verified locally | Content and interaction only |
| Workcell onboarding (Overview → Onboard → Twin → Sim → Real → Runs) | Implemented | Physical readiness always shown as unverified; no device connection |
| Workflow judgment course | Verified locally | English synthetic-only review, repair, trial, scripted reconciliation and conclusion; see [course contract](WORKFLOW-JUDGMENT-COURSE.md). 539 backend tests and 45 browser journeys passed; see [validation](VALIDATION.md) |
| Flex and OT-2 introductions + visual Workflow Studio | Verified locally | Public chaptered animations, editable blocks and instrument-specific decks; free designs use model checks without a prescribed lesson target. See [studio contract](INSTRUMENT-STUDIO.md) |
| Page-level code splitting | Implemented | Main bundle ~374 kB including public instrument illustrations; studio remains lazy loaded |

## Sim–Real connector development

| Area | State | Notes |
|---|---|---|
| Connect an instrument page | Implemented and tested locally | English Mac setup with chip selection, pairing, fresh probe, exact-plan preflight, refresh and unknown-outcome recovery; included in the normal application release |
| Machine control plane and companion | Implemented locally | Scoped credentials, atomic device locks, local operator confirmation, immutable receipts and no automatic replay; fixtures are software evidence |
| Flex / OT-2 protocol compiler | Verified in Opentrons 9.0 software simulator | Both execute pickup, aspiration, dispense and drop with actual labware definitions; no native Matterix or physical validation |
| Mac desktop bundle | Local candidate | Includes Python; signing/notarization and actual installation acceptance remain pending |
| AC GitHub → private S3 | Mechanism implemented | Candidate intake and reviewed immutable publication; no approved artifacts, credentials or S3 writes from this change |
| Physical workflow enablement | **Blocked** | Requires approved connector/installer, actual SiLA/calibration and robot commissioning, and same-plan native DT qualification. OT-2 also lacks required runtime identity and native asset support |

See [connector setup and acceptance](connectors/SETUP.md). Physical execution is
disabled by default and no robot was operated during this implementation.

## AWS (account 247893369214, ca-central-1)

| Area | State | Notes |
|---|---|---|
| CloudFront, S3, API Gateway, Lambda, DynamoDB, Cognito | Verified | 54 resources applied; post-apply plan clean |
| utoronto.ca self-registration | Verified (infrastructure) | Real signup, mailbox confirmation, sign-in and two-account isolation are deferred by the user (2026-10-23); runnable harness: [learner acceptance](LEARNER-ACCEPTANCE.md) |
| Machine API, worker authorizer, lease reaper | Verified with synthetic workers | Smoke test: 21 assertions |
| Automatic release on `main` | Verified for the prior main release; current update under validation | Latest existing CI/deploy runs succeeded. Install phases now have separate time bounds and logs; release checks bind runtime version and archive checksums |
| Academy 0.2.0 / internal Flex GPU acceptance | AWS application deployed; GPU blocked | Four Lambda hashes and 35 web files verified at source `674c1e2`; global gate stays false. Applied AWS GPU quota is now 8 vCPU; the 16-vCPU request remains CASE_OPENED. A guarded g6.2xlarge capacity trial is prepared; see [capacity trial](GPU-CAPACITY-TRIAL.md). Native browser acceptance is deferred with real account acceptance. See [live record](DEPLOYMENT-2026-10-20.md) |
| Native gate in release | Implemented | `release.py` requires the Lambda gate to equal `NATIVE_EXECUTION_EXPECTED` (default `false`) |
| Alarm notifications and budget | Notifications verified; Academy budget disabled | 13 operational alarms target a confirmed SNS subscription. Controlled ALARM and OK emails arrived. The requested US$400 account budget was removed at the user's request; the existing organization budget was preserved |
| Lambda concurrency | Capacity acceptance pending | Applied quota remains 10 with learner limit 5 requests/s. Increase request 209df9a3cc9940ba8adbe5f47e9ee2e4Y7CXjacq is CASE_OPENED; do not claim cohort capacity before approval and authenticated load acceptance |

## Native simulation (Matterix / Isaac on Ubuntu)

| Area | State | Notes |
|---|---|---|
| Single EC2 Ubuntu GPU pilot | Authorized capacity trial | Existing SDL0-DEV1 development account; sequential build and acceptance, at most one GPU. Installed image/render capacity and real browser workflow remain separate gates. See [capacity trial](GPU-CAPACITY-TRIAL.md) |
| Pinned `mix_four_vials` adapter, journal, supervisor | Implemented | Fixed recipe; only the seed is learner-selectable |
| Workflow Studio → native Flex | Implemented | Saved layout, action order, volumes and initial amounts compile into `workflow-studio-flex`; native observations, run-bound video, recovery and verified cleanup are wired. CPU/browser fixtures and a local GPU probe are prepared; no real GPU/browser acceptance is recorded. See [Studio native acceptance](STUDIO-NATIVE-ACCEPTANCE.md) |
| Workflow Studio → native OT-2 | **Blocked** | OT-2 teaching designs work; the approved Flex asset pin has no OT-2 robot. A reviewed OT-2 image, deck mapping and separate qualification are required |
| Learner first-transfer → native intent + scene preflight | Implemented | `native_plan.py`. Submission and claim reject plans a qualified scene cannot run exactly as saved. No native executor for this scene exists yet |
| KVS WebRTC media (MASTER/VIEWER grants, relay-only ICE) | Partly verified | KVS signaling and TURN credentials verified with a temporary channel; no real Isaac frames |
| Host agent install on the lab Ubuntu | **Blocked** | Tailscale SSH denies the operator account; Isaac Lab checkout is owned by another user (Git ownership check fails). See [ENDPOINT-COMMUNICATION.md](ENDPOINT-COMMUNICATION.md) for the proposed route that does not depend on SSH |
| Worker qualification, native gate on | **Blocked** | Requires a working GPU host and the scene-specific acceptance records in [MATTERIX-CONTRACT.md](MATTERIX-CONTRACT.md). A bounded Studio commissioning grant permits only two approved designs on one worker while the global gate stays off; it does not qualify the worker |

## Open housekeeping

- The enrolled machine credential for `borealis-flex-mixing` sits in ignored `build/native-installer/`. Move it to the host's credential store after install, or revoke and re-enroll if the install route changes.
- `Claude outputs/dashboard-nav.patch` is an unapplied navigation-animation patch from an earlier session; apply or discard deliberately.
- Earlier workcell onboarding shipped in [PR #4](https://github.com/SissiFeng/matterix-academy/pull/4). The course, image preparation and current readiness fixes are tracked in [PR #5](https://github.com/SissiFeng/matterix-academy/pull/5); publication is verified separately by the deployment workflow and the live version manifest.
