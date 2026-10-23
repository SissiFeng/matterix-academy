# Live learner acceptance

The `acceptance:learners` harness verifies the deployed English learner experience against real Cognito and the real owner-scoped API. It creates only synthetic teaching records. It never submits a native run, qualifies a worker, creates accounts through an administrator API, or substitutes local guest authentication for Cognito.

**Current evidence:** the harness and its local guard tests are implemented. Real account acceptance was deferred by the user on 2026-10-23 and has not been executed. Local tests do not establish registration, email delivery, cloud learner isolation, or authenticated browser acceptance.

## Preconditions

- Deploy the tested Academy release and check its `/version.json` and `/api/health` first.
- Use Node 22.12 or newer and the installed Playwright Chromium browser.
- Arrange two different, dedicated QA learners. Learner A must not already have a Flex first-transfer lesson. Use a fresh account when possible; the harness stops before course/experiment changes if it finds an existing Flex lesson.
- One person must be able to perform the normal Cognito signup, email confirmation and login. The application currently permits the email domains shown on its welcome page. Do not weaken that policy for this test.
- Learner B must use another real Cognito subject. A second browser profile for the same account does not test isolation.
- Allow time for three manual authentication stages: learner A, learner B, then the same learner A again in a fresh browser context. Each stage waits five minutes by default (30–900 seconds configurable).

No credentials, OTPs or account email addresses should be placed in commands, shell history, environment variables, or the evidence directory. Type them directly into Cognito's browser forms.

## Run

From the repository root, with both QA account holders available:

```bash
export ACADEMY_LEARNER_URL='https://d2m3yolcjdy6d2.cloudfront.net'
export ACADEMY_LEARNER_OUTPUT="$HOME/.codex/artifacts/matterix-academy/learner-acceptance-2026-10-23"
npm --prefix app/frontend run acceptance:learners -- --confirm-live --dedicated-qa-accounts
```

The harness opens separate browser contexts for the two learners. The console and the private report identify the current stage. Complete signup/email confirmation for a new learner A if registration is part of the acceptance; otherwise sign in normally. The harness controls the teaching UI after authentication, so leave the browser alone until the next authentication prompt.

`ACADEMY_LEARNER_LOGIN_TIMEOUT=600000` allows ten minutes per manual login stage. A timeout fails the attempt; it does not bypass authentication or submit another command.

The normal run preserves any existing workflow-course answers by stopping. To intentionally replace the singleton workflow course of a **dedicated QA account only**, add `--restart-qa-course`. This is not appropriate for a learner's personal account. The Flex lesson preflight still requires an unused learner. Experiments created by the test are retained and identified in the report; the harness does not delete learner history.

## Checks and evidence

The live sequence checks:

1. Two verified-email Cognito identities and successful authenticated profile reads, with distinct subjects.
2. Normal onboarding for new learners and `Can this workflow run?`: identify gaps, repair, save, refresh without another mutation, run the 12-action synthetic trial, reconcile, and complete the evidence-bounded conclusion.
3. A dilution experiment created and saved through the UI, deck placement preserved after refresh, a successful 12-action run, reset, and a successful second run.
4. The first-transfer equipment tour, preparation, prediction, four teaching actions, and correct reflection.
5. Learner B's inability to read, replace or reset learner A's experiment (404), unchanged owner records, unchanged B course/session records, and rejection of a stale course version (409).
6. UI logout, then a new isolated browser context and a fresh Cognito sign-in for A. The saved course and completed experiment must match the original cloud records exactly.
7. Explicit course restart and persisted clearing of the synthetic trial.

Signup and confirmation form submissions are observed only at the configured Cognito origin. These observations are informational: failed forms can return HTTP 200, and a learner can subsequently sign in with an existing verified account. Therefore neither outgoing submissions, successful-looking page responses, nor verified-email login can set `new_signup_and_email_confirmation` to true. The harness never reads form bodies, passwords, confirmation codes or email addresses. Its account evidence contains only a subject SHA-256 pseudonym and observation booleans.

**Registration and mailbox delivery require separate real operator evidence.** During the real acceptance, record that a new allowed-domain account was successfully created, that the confirmation message arrived in its mailbox, and that the code was accepted. Bind that observation to the report's acceptance ID and account pseudonym, with the observer and time. Do not include email contents, passwords or codes. Until that independent evidence is reviewed, `new_signup_and_email_confirmation` remains false, `email_delivery` remains `not-observed-by-browser-harness`, and the overall browser report remains `incomplete` even when `automated_status` is `passed`. Do not edit generated report values to manufacture a pass; keep the operator observation as a separate acceptance artifact.

The sanitized `learner-report.json` is written atomically with mode 0600 in a mode-0700 directory. Browser contexts are nonpersistent and isolated; closing them discards browser credentials. There are no auth exports, traces, HAR files, screenshots, or token-bearing error strings. On failure the report names the stage and error type only. A failed mutation is never automatically replayed; inspect saved server state before deciding whether a new acceptance attempt is appropriate.

Exit codes: 1 = failed check or timeout; 2 = completed automatic checks with independent registration/email evidence pending. The current browser harness intentionally cannot produce a complete registration acceptance by itself. No outcome establishes native Isaac/GPU, hardware, chemical, or multi-user load acceptance. Use the native commissioning and load-test procedures for those separate gates.

## Local verification

These checks need no AWS resources or real accounts:

```bash
npm --prefix app/frontend run test:acceptance
node --check app/frontend/learner-acceptance.mjs
npm --prefix app/frontend run format:check
npm --prefix app/frontend run test:e2e -- tests/learner-acceptance.spec.ts
```

The guard tests cover origin restrictions, bounded teaching-only API paths, Cognito origin/method attribution, distinct verified identities, cross-owner denial without mutation, synthetic evidence, failed signup followed by existing-account login, incomplete registration status, and protected evidence directories. `tests/learner-acceptance.spec.ts` runs the exact shared course, dilution and first-transfer UI journeys against the local real app and backend, including accessible selectors, saves, refresh, reset and repeat. This catches selector drift without mocking results; it is local synthetic coverage and does not establish live Cognito or email acceptance.
