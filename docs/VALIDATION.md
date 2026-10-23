# Academy readiness completion — 2026-10-23

The final local verification passed **514 backend tests and 43 Chromium journeys**,
including a five-learner concurrent SQLite/FastAPI regression and the exact shared
course, dilution reset/repeat and first-transfer helpers used by the live learner
harness. Its nine guard tests also passed; failed registration followed by existing
account login can never establish a successful new registration.

`build-lambda.sh`, `verify.sh`, frontend build/format, both Terraform roots and the
actual offline Amazon Packer plugin schema passed. The packaged health/OpenAPI and
release manifest now share version 0.2.0, and publishing checks the installed ZIP
version before credentials plus the live version after deployment. CI installation
has separate bounded OS/browser phases and retained failure logs.

Security and architecture review identified two live-harness errors: stale accessible
selectors and request-only registration evidence. Both were corrected; the shared
real-app regression passes. The new GPU-capacity path also received a separate
launch-blocking review with no remaining finding. These are local/review results,
not fresh remote CI, image-build or native acceptance evidence.

Operational Terraform applied 13 additions and four alarm updates, then removed
only the new US$400 budget at the user's request. The final plan has no changes.
All 13 operational alarms have a confirmed SNS target; controlled ALARM and OK
messages were observed in the operator mailbox. The organization budget was
preserved. [Sanitized operational evidence](evidence/operations/2026-10-23.json).

Applied G/VT quota is now 8 vCPU; g6.2xlarge preflight passes the 32-GiB/full-L4
minimum. Actual image startup/render capacity remains unmeasured until the bounded
build in [GPU-CAPACITY-TRIAL.md](GPU-CAPACITY-TRIAL.md). Real registration, sign-in,
two-user cloud isolation, authenticated load and browser/native DT acceptance are
**deferred by the user**. Their harness is ready in [LEARNER-ACCEPTANCE.md](LEARNER-ACCEPTANCE.md),
but no local result promotes those live acceptance gates.

# Academy 0.2.0 and GPU image preparation — 2026-10-19

The complete Isaac dependency resolution exposed a conflict missed by top-level
version comparison: Sim 6.0.1.0 requires torchvision 0.26.0, which requires torch
2.11.0. The candidate is corrected to torch 2.11.0+cu128 / torchvision 0.26.0+cu128.
Lab also requires Pydantic <2.12, so the native environment uses 2.11.10 and the
independent Academy agent retains its existing frozen 2.13.5. No private repository
was modified to force compatibility. Older dated candidate notes below are historical.

Linux CPython 3.12 / manylinux_2_35 resolution produced a **245-package hashed
runtime lock**. Frozen Academy export produced a **39-package agent closure**.
Both passed hash-enforced Linux install dry runs; this does not prove an actual
Linux installation. The sdist-only flatdict build uses pinned bootstrap tools.
The official 595.58.03 driver installer was downloaded outside Academy and verified
against the publisher's SHA256. It was not installed and licenses were not accepted.

Private engine and materialized LFS assets were exported to a protected external
input directory, then restored in a temporary directory. The restored sources passed
exact commit, clean Git tree, fixed-scene and materialized-payload checks. No local
Git credential helpers, remotes, hooks, untracked files or external data submodule
were exported. Source repositories remain independent and unchanged.

The Packer 1.16.1 / Amazon plugin 1.8.3 recipe passed formatting, syntax and full
plugin-schema validation in a temporary copy with fake credentials/inputs and
blocked cloud connectivity. The full schema check caught an unsupported account
attribute, which was replaced with an explicit guarded build wrapper. The wrapper
verifies the exact frozen credentials through a pinned official STS endpoint before
Packer; tests cover a spoofed STS override and wrong-account rejection. This wrapper
was not run against AWS. Build consent and license flags default false.

Architecture review's bootstrap-hash extraction and worker-readability findings
were fixed and regression-tested. Security review's IMDS token-probe improvement
and STS endpoint finding were also addressed. No deferred review blocker remains.

**Local verification:** 482 backend tests, 42 Playwright journeys, lint/format,
frontend build, Lambda packaging, both Terraform validations and the disabled
zero-resource plan passed. Packer schema validation uses no real account or build.
The actual GPU image, installed driver, scene/render probe, browser/native video,
five-step workflow and reset/recovery acceptance have **not run**. Neither local
source release nor image inputs deploy the existing Onboarding application.

See [GPU-IMAGE-BUILD.md](GPU-IMAGE-BUILD.md) and [COMMISSIONING.md](COMMISSIONING.md).

---

# Internal Flex commissioning preparation — 2026-10-19

Compatibility was rechecked against clean internal Flex code at
`18a96b78ee989fbf4e480e9db6a588c148c6adbe` and internal assets at
`c57f12a04079a5f99405e1fcb818a3b7ccc52e5b`, not the unrelated OT2 checkout.
The earlier Lab 2.3 / Sim 5.1 candidate is superseded by the pinned Python 3.12 /
Lab 3.0.0b2.post1 / Sim 6.0.1.0 profile. Public wheel metadata and source audit
are retained under `docs/evidence/ec2-gpu/`; source audit passes pins/payloads
but correctly fails runtime/GPU readiness on the local Mac.

`bash scripts/verify.sh` passed **463 backend tests**, lint/format, frontend
build/format, the live-harness response-correlation unit test and both Terraform
validations, including an isolated disabled plan with **zero resources**.
All **42 Playwright browser journeys passed** (1.7 minutes), including the
explicitly synthetic commissioning submit/refresh/cleanup journey. It checks the
control path without asserting native video or qualifying its fixture worker.
`bash scripts/build-lambda.sh` passed. After tightening operator preflight input
validation, the 20 commissioning/evidence tests and Lambda packaging passed again.
The live harness now follows actual POST submission and session remote-run polling
URLs, rejects unrelated/stale responses, and checks origin. This corrects the
architecture review finding. Security review found no concrete findings.

No cloud administrative write, live browser commissioning, Isaac runtime execution,
AMI build or resource creation was performed. The native frame proof, decoded video,
cleanup and two-run browser acceptance still require an authorized GPU host.
The browser/evidence checker never sets qualification; image provenance, isolation
and interruption/recovery remain independent operator acceptance requirements.
See [COMMISSIONING.md](COMMISSIONING.md) for the complete procedure.

---

# EC2 GPU pilot preparation validation — 2026-10-19

Prepared in the attached `workflow-readiness-course` worktree without selecting an
AWS account or creating paid resources. The public AWS Linux On-Demand/EBS price
snapshot and hashes are saved in `docs/evidence/ec2-gpu/prices-2026-10-19.json`.
This work adds an independent default-disabled `infra/ec2-gpu` root, a prepared-image
contract, fixed-runner service, manifest renderer and acceptance matrix.

`bash scripts/verify.sh` passed: **436 backend tests**, Ruff lint/format,
TypeScript/Vite build, Prettier and both Terraform roots' validation. This includes
**19 new offline preparation tests** on image pin validation, runner schema
compatibility, price arithmetic/catalog gaps and rejecting the pending acceptance
template as a qualification record. `bash scripts/build-lambda.sh` passed.
`bash -n scripts/verify-ec2-gpu.sh` and `git diff --check` passed.

`bash scripts/verify-ec2-gpu.sh` passed a fresh-state disabled plan with zero
resources and no account discovery; it was also tested with ambient
`TF_VAR_enabled=true` and an invalid AWS profile to verify the command-line false
opt-in and profile isolation. Terraform 1.5.7 / locked AWS provider 6.66.0 were used.
Independent security/architecture reviews reported no findings in this preparation
scope. Current changes do not alter browser flows; the preceding course's 41
Chromium journeys remain the separately recorded browser evidence, not GPU proof.

No enabled/live Terraform plan, apply, EC2 launch, AMI build, worker enrollment,
qualification, KVS probe/channel creation, native gate change, GPU frame, actual
browser-to-Isaac run, native recovery or physical validation occurred. The exact
approved image/accounts/network inputs and supervised GPU commissioning remain
prerequisites. See [the pilot runbook](EC2-GPU-PILOT.md).

# Workflow judgment course validation — 2026-10-19

Validated locally in the attached `workflow-readiness-course` worktree against
baseline `1e7f767` plus the uncommitted course changes. `bash scripts/build-lambda.sh`
passed and produced the Python 3.12 / Linux x86_64 Lambda package.
`bash scripts/verify.sh` passed: **417 backend tests**, Ruff lint/format, TypeScript /
Vite production build, Prettier, Terraform formatting and configuration validation.
Terraform used a fresh temporary `TF_DATA_DIR` with backend-disabled initialization;
no AWS account selection or infrastructure apply occurred. Node 22.15.0 was used.

All **41 Chromium journeys passed**, including five new course journeys. Course
coverage includes incorrect gap/repair/recovery/conclusion answers, complete flow,
refresh resume, restart, stale records, unsaved navigation, lost save response without
replay, blocked reconciliation and recovery, and a 390px dark-theme viewport.
Ten new backend cases run across SQLite and mocked DynamoDB, covering synthetic
trial results, stage enforcement, forged-result rejection, version conflicts,
authentication, ownership and origin isolation. Security and architecture reviews
reported no findings. Desktop completion and mobile dark review screenshots were
visually inspected; neither viewport showed horizontal overflow.

The written explanation is not scientifically graded: completion requires the
correct evidence-boundary choice and a nonblank explanation of at least 20 characters.
All numerical and incident evidence is synthetic. No CI run, commit, push, AWS
publication, native Isaac/GPU run or physical-device acceptance is established.
Local preview uses loopback ports 5176/8003 and a separate demonstration database.
See [the course contract](WORKFLOW-JUDGMENT-COURSE.md).

# Repository fixes and preflight validation — 2026-10-16

Branch `codex/workcell-onboarding` (local, not pushed). Backend: **407 passed** with the `native-worker` extra on Python 3.12 (Linux, cloud workspace); 394 passed + 13 `aiortc` skips on the Linux VM. Ruff lint/format, TypeScript, Prettier and `scripts/build-lambda.sh` passed. Vite main bundle fell from about 521 kB to 344 kB with no size warning.

Playwright: **35 of 36 journeys passed** against a preinstalled Chromium build 1194 (the pinned Playwright expects 1228, which could not be downloaded here). `workcell.spec.ts` "workspace pages fit a phone…" fails identically on the unmodified baseline commit `3e27fca` in this environment, so it is not attributed to this change; re-run on the pinned browser. Lazy loading exposed a real race in `SimulationLab` (a deep-link hash change before the lazily loaded page attached its listener); fixed and repeated 3× green.

Terraform: all `.tf` files parse (python-hcl2). `terraform fmt`/`validate` could not run because no Terraform binary was reachable from either workspace; CI runs both. The new alert and budget resources default to off, so the existing plan is unchanged until variables are set.

No AWS account was selected, nothing was deployed, and no native, GPU, media or physical behavior is established by this change.

# Workcell onboarding workspace validation — 2026-10-02

Verified locally against baseline `9840ed7` plus the uncommitted workcell onboarding changes: **392 backend tests** and **36 Chromium journeys** passed. The added coverage exercises owner-scoped device declarations on SQLite and mocked DynamoDB, version conflicts, concurrent atomic twin creation, rejected client-supplied authority fields, reset invalidation and the separation of teaching results from physical readiness. Five new browser journeys cover wizard persistence, the paired teaching execution loop, lost-receipt reconciliation without replay, conflicting edits, unsaved navigation and step protection, old paired trials outside the recent list window, deep links, and 390px layouts.

`scripts/build-lambda.sh` produced the Linux x86_64 package. `scripts/verify.sh` passed with an empty temporary `TF_DATA_DIR`; the existing cached Terraform backend otherwise requested S3 credentials despite backend-disabled initialization. No AWS account was selected and no infrastructure operation was run. The final frontend build/format checks and all browser journeys were repeated after the route and wizard protection changes. The build reports a non-fatal main-bundle size warning (about 521 kB before gzip); the two existing upstream Python deprecation warnings remain.

Desktop and phone Twin screenshots were inspected. The in-app browser completed a separate local guest flow, registered **Demo Flex / Demo workcell**, declared its intended capabilities, created its paired teaching session and opened the Twin view. This preview uses `.data/workcell-preview.sqlite` on loopback ports 5175/8002 and contains demonstration records only. Physical values remained unknown and physical execution remained disabled.

This is local application and synthetic teaching evidence. No commit, push, CI run, AWS publication, live device connection, native Isaac/GPU execution, synchronization or physical validation is established by this change. See [workcell onboarding](WORKCELL-ONBOARDING.md) for implemented behavior and limitations.

# AC deployment and outbound worker validation — 2026-10-01

The control plane and learner site are deployed to AC account 247893369214 in ca-central-1. Initial deployment-time local validation passed **194 backend tests and 23 Chromium journeys**, plus Lambda packaging, frontend build and Terraform validation. Terraform created 54 resources and the post-deployment plan has no changes. Live machine authentication/revocation and DynamoDB persistence/conditional rollback passed. Learner handler checks used synthetic authorizer context; actual Cognito login, two-real-user isolation and all native/GPU/media acceptance remain pending. Native execution is disabled. See [the deployment evidence record](DEPLOYMENT-2026-10-01.md) for exact scope and artifacts. Earlier entries below describe their historical validation boundaries.

# Connector developer views validation — 2026-10-01

Verified against committed baseline `1727cc4` plus the connector developer changes: **149 backend tests** and **21 Chromium journeys** passed. The three added journeys exercise native-to-SiLA mapping dimensions, temperature acceptance versus completion, live-property and error semantics, native interface choices, the six-stage development sequence, scenario feedback, subpage reload/sidebar navigation and 390px layouts. Frontend build and formatting passed after the final navigation fix.

Validation used an isolated source copy and dedicated test ports because unrelated remote-execution backend and infrastructure changes were being edited in the shared checkout. Those uncommitted changes are outside these results. `scripts/verify.sh` and `scripts/build-lambda.sh` passed in that copy. The twelve new displayed excerpts and the five existing excerpts were checked byte-for-byte against connector commit `2a9c3004400325d7816c80065a2282a4ad6b5b70`. Architecture review's subpage URL finding was fixed, regression-tested and rechecked.

The SDK examples describe the actual Flex connector. HTTP and device-protocol examples illustrate development choices; they do not implement new transports. Feature names are repository-specific custom contracts, not a claim that all SiLA devices are interchangeable. Browsing the development stages does not run connector tests, commission hardware or deploy a server. No fresh manual visual, AWS, GPU or physical-device acceptance was performed.

# Discovery learning validation — 2026-10-01

Verified locally: **149 backend tests** and **18 Chromium journeys** passed. New coverage exercises the owner-scoped SQLite/mocked-DynamoDB notebook, optimistic version conflicts, serialized storage bounds, research filters and primary-source links, adaptation into a persisted design brief, method ordering, scenario reasoning, same-design concurrent edits, lost save responses, cancelled navigation without session creation, delayed creation with draft locking and retained history, connector source/trace interactions, reload and 390px layouts.

`scripts/verify.sh` passed Python lint/format, backend tests, TypeScript/Vite build, frontend formatting and Terraform validation. `scripts/build-lambda.sh` produced the Linux x86_64 archive. No deployment was performed. The two existing upstream Python deprecation warnings remain.

Security review found no introduced vulnerabilities. Architecture review identified orphan experiment creation after cancelled navigation and same-design overwrite after conflict reload. These and delayed-creation navigation/result handling were fixed with regression journeys. The five displayed connector excerpts were compared byte-for-byte with the pinned committed source, independent of the connector checkout's uncommitted edits.

Research evidence consists of six manually curated primary papers and linked official Flex documentation. Marketplace search filters that local collection; there is no live literature crawler. Gantry diagrams, connector playback and illustrative measurements are educational, not executed native simulation or experimental results. Paper adaptations are design-only and cannot be submitted to the execution runner. The previous manual visual, Ubuntu/GPU and AWS qualification limits remain in effect.

# Synchronized run contract validation — 2026-10-01

Verified locally: **139 backend tests** passed. New coverage binds whole-workflow inputs to a run, distinguishes acknowledgement from confirmed progress, rejects cross-run/out-of-order reports and rewritten native observations, requires ordered completion evidence, and recovers a lost start response through the original run ID without another POST. Both specialist reviewers identified observation-integrity gaps; these were fixed, regression-tested and rechecked.

The **10 Chromium journeys** also passed during this change; the student interface continues to use the teaching runner. `scripts/verify.sh` and `scripts/build-lambda.sh` passed after the final backend fixes. All remote-run responses in these tests are HTTP fixtures. The Ubuntu implementation, native scene/action/observation mapping, durable orchestration, live student progress and media integration are still pending. This is contract validation, not a working Academy-to-Matterix synchronization demonstration.

# English interface validation — 2026-10-01

All student interface copy is now English, including course content, diagram labels, accessibility labels, dialogs, readiness checks, assessments and remote connection messages. Exact legacy system-generated titles and assessment labels are translated on read; stored outcomes, learning progress and custom learner titles are preserved.

Verified locally: **111 backend tests** and **10 Chromium journeys** passed, including the complete English first-transfer lesson, mobile overflow checks and legacy-record preservation. `scripts/verify.sh` and `scripts/build-lambda.sh` passed. The local preview API was restarted to serve the updated responses. This remains automated browser evidence; the previously documented remote, deployment and manual visual acceptance limitations still apply.

# Guided first-transfer validation — 2026-09-30

Verified locally for `codex/flex-guided-learning`:

- **110 backend tests passed**, across SQLite and mocked DynamoDB. New coverage checks 50/100 µL transfers, preparation and prediction gates on start/resume, learning ownership/versioning, edit invalidation, reset answer preservation, fixed D3 fixtures, and remote client uncertainty/recovery by caller-known IDs.
- **10 Chromium browser journeys passed**. The five new journeys cover the full equipment-to-reflection lesson and 50 µL challenge, mobile overflow and unavailable remote status, unsaved prediction/discard behavior, prediction feedback independent of prerequisites, and a committed action whose response is lost without automatically replaying it. The original five dilution/account/navigation journeys still pass.
- `bash scripts/verify.sh` passed: Python lint/format, backend tests, TypeScript/production build, frontend formatting and Terraform initialization/validation. No AWS plan or apply was run.
- `bash scripts/build-lambda.sh` produced a Linux x86_64 Python 3.12 archive; it was not invoked in AWS.
- Security review reported no findings. Architecture review findings were fixed and rechecked, with regression coverage for archived answers, discarded inputs, prediction feedback and remote request-ID reconciliation.

This revision has automated browser evidence, but no fresh manual visual acceptance: the app browser returned a local-URL policy rejection during the preceding preview attempt. The tests do not establish the appearance of a live 3D scene.

Still unverified/unimplemented: actual Ubuntu gateway server, native Matterix adapter, durable remote operation orchestration, lease/queue scheduling, authenticated streaming, GPU execution, classroom concurrency and deployed AWS identity/network behavior. `/api/remote/status` deliberately reports remote execution unavailable even after a successful capability response. Gateway tests use a mock HTTP transport.

The two existing upstream Python deprecation warnings remain. Consult GitHub Actions for live CI status and the commit tested; these dated results are local evidence.

# Initial release validation — 2026-09-28

Verified locally in this development session:

- **81 backend tests passed**, covering both SQLite and mocked DynamoDB. These include mass/solute conservation, target concentrations, invalid actions, reset, pause/resume, stale and simultaneous mutations, ownership, profile persistence, AWS identity claims, gateway qualification, chronological history beyond 50 records, empty-container tiny-volume input, and floating-point roundoff.
- **5 Chromium browser journeys passed**: onboarding-to-completed-dilution, save/refresh/reset/single-step, useful no-tip failure, mobile layout, unsaved navigation/dialog keyboard handling, and delayed response isolation when switching experiments.
- TypeScript and production frontend build passed. Frontend formatting and Python lint/format passed.
- Terraform provider initialization and `terraform validate` passed using Terraform 1.5.7 and AWS provider 6.66.0. No AWS plan or apply was run.
- The Lambda deployment archive was built with Linux x86_64 Python 3.12 wheels (approximately 19 MB compressed). It was not invoked in AWS Lambda.
- The local welcome, onboarding, course and experiment interfaces were opened and visually inspected in a browser.
- Independent security and architecture reviews completed. Three concrete architecture/input/concurrency findings were fixed, received regression coverage and were rechecked.

Two upstream Python deprecation warnings are currently emitted by Mangum/Starlette test support; tests pass. They do not imply cloud runtime validation.

Not established by these checks: deployed Cognito login, real DynamoDB/IAM behavior, AWS billing/quota readiness, a running Ubuntu gateway, Isaac/GPU execution, authenticated 3D streaming, classroom concurrency or physical robot safety. The student UI explicitly keeps live Matterix unavailable.

For current remote CI status, inspect the repository Actions page rather than treating this dated local report as live evidence.
