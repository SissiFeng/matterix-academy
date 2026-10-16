# Status

Single source for current project status. Updated 2026-10-16. Dated evidence lives in [VALIDATION.md](VALIDATION.md) and [DEPLOYMENT-2026-10-01.md](DEPLOYMENT-2026-10-01.md); this page only summarizes it. When this page and an older document disagree, this page wins and the older document should be corrected.

Legend: **Verified** = observed in a real environment. **Implemented** = code and automated tests exist; no real-environment evidence. **Blocked** = waiting on something outside this repository.

## Learner application

| Area | State | Notes |
|---|---|---|
| Teaching-model lessons (first transfer, dilution sandbox) | Verified locally | Synthetic by design; never labeled as Isaac or physical |
| Discovery studio, workflow marketplace, connector explorer | Verified locally | Content and interaction only |
| Workcell onboarding (Overview → Onboard → Twin → Sim → Real → Runs) | Implemented | Physical readiness always shown as unverified; no device connection |
| Page-level code splitting | Implemented | Main bundle ~344 kB (was ~521 kB) |

## AWS (account 247893369214, ca-central-1)

| Area | State | Notes |
|---|---|---|
| CloudFront, S3, API Gateway, Lambda, DynamoDB, Cognito | Verified | 54 resources applied; post-apply plan clean |
| utoronto.ca self-registration | Verified (infrastructure) | A real learner sign-in and two-account isolation test are still owed |
| Machine API, worker authorizer, lease reaper | Verified with synthetic workers | Smoke test: 21 assertions |
| Automatic release on `main` | Implemented, flaky | One run stalled installing Playwright system packages; workflows now bound and retry that step |
| Native gate in release | Implemented | `release.py` requires the Lambda gate to equal `NATIVE_EXECUTION_EXPECTED` (default `false`) |
| Alarm notifications and budget | Implemented, off | Set `alarm_email` / `monthly_budget_usd`, review and apply the plan. The budget filter requires the `Application` cost-allocation tag to be activated |
| Lambda concurrency | Risk | Account quota is 10 and shared with other workloads. Request an increase before a cohort |

## Native simulation (Matterix / Isaac on Ubuntu)

| Area | State | Notes |
|---|---|---|
| Pinned `mix_four_vials` adapter, journal, supervisor | Implemented | Fixed recipe; only the seed is learner-selectable |
| Learner first-transfer → native intent + scene preflight | Implemented | `native_plan.py`. Submission and claim reject plans a qualified scene cannot run exactly as saved. No native executor for this scene exists yet |
| KVS WebRTC media (MASTER/VIEWER grants, relay-only ICE) | Partly verified | KVS signaling and TURN credentials verified with a temporary channel; no real Isaac frames |
| Host agent install on the lab Ubuntu | **Blocked** | Tailscale SSH denies the operator account; Isaac Lab checkout is owned by another user (Git ownership check fails). See [ENDPOINT-COMMUNICATION.md](ENDPOINT-COMMUNICATION.md) for the proposed route that does not depend on SSH |
| Worker qualification, native gate on | **Blocked** | Requires the host install and the acceptance records in [MATTERIX-CONTRACT.md](MATTERIX-CONTRACT.md) |

## Open housekeeping

- The enrolled machine credential for `borealis-flex-mixing` sits in ignored `build/native-installer/`. Move it to the host's credential store after install, or revoke and re-enroll if the install route changes.
- `Claude outputs/dashboard-nav.patch` is an unapplied navigation-animation patch from an earlier session; apply or discard deliberately.
- Branch `codex/workcell-onboarding` holds the workcell work and this round of fixes; it is local until pushed and reviewed.
