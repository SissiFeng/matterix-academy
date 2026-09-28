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
