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
