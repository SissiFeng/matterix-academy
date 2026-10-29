# Can this workflow run?

A 15–20 minute English course at `/#/workflow-course`, entered from Learning lab.
Learners review an agent-proposed serial dilution, find evidence gaps, repair the
teaching plan, run it, reconcile a fictional lost response and submit a conclusion.

## Learning path

1. **Review:** identify insufficient source liquid (50 µL for a 100 µL first
   transfer), an unsupported explicit mixing command, and an unsupported claim
   that a teaching pass grants physical approval. Three tips and a 300 µL teaching
   capacity are sufficient; selecting these distractors does not pass review.
2. **Repair:** supply at least 100 µL of stock (up to the existing 1,500 µL model
   bound) and use ideal instantaneous mixing as an explicit teaching assumption.
3. **Practice:** the backend reuses the existing dilution teaching calculator for
   12 actions. It saves action events, final state and concentration/tip checks.
   Targets are 50%, 25% and 12.5%. No native runner or physical device is called.
4. **Reconcile:** a separate, visibly scripted dispense timeout leaves its outcome
   unknown. Retry and assumed success are rejected. Reading the fictional original
   command record reveals one completion. This does not simulate a real transport
   or establish any observation about a device.
5. **Conclude:** select synthetic-only acceptance and provide a 20–600 character
   explanation. Choice correctness and explanation presence are checked; prose
   correctness is not automatically graded. Completion grants no hardware authority.

Wrong answers are saved with feedback and remain at the current stage. Stages cannot
be skipped through the API. Refresh resumes the saved stage, answers and trial.
Restart explicitly clears the current exercise, including trial and explanation;
prior exercises are not retained. No certificate is issued.

## Persistence and failure behavior

`GET /api/workflow-course` reads the authenticated owner's record (revision zero
before first save). `POST /api/workflow-course` accepts a strict bounded command and
`expected_version`. The record uses `course#workflow-readiness`, separate from
`session#` records and native runs. Server-owned phase, trial, evidence and completion
cannot be supplied as writable claims. Both SQLite and DynamoDB use existing atomic
conditional writes. AWS identity uses the existing API Gateway authorizer dependency.

Unsaved form changes warn before navigation. During a pending mutation, controls are
disabled. If the response is lost or a write conflicts, the UI reads the same record
without replaying the command. If that read also fails, edits remain blocked until a
read-only reload succeeds. Navigation away never causes an async response to redirect
back into the course.

## Evidence boundary and validation

All evidence is synthetic. Geometry, reachability, actual mixing, chemical outcomes,
calibration, native Isaac/GPU behavior and physical execution are not evaluated.
The existing Ubuntu qualification gate and real-device authorization are unchanged.

Acceptance tests are in `test_workflow_course.py` (SQLite and mocked DynamoDB) and
`workflow-course.spec.ts` (real local API and Chromium). The browser tests cover
completion, incorrect answers, refresh, restart, unsaved navigation, stale writes,
lost responses, blocked reconciliation and a narrow dark-theme viewport.

Run the Lambda packaging script, `scripts/verify.sh`, and all frontend Playwright
journeys. These checks establish local software behavior, not deployed AWS, GPU or
hardware acceptance.

Inspired by the capability-development and human intervention discussion in
[Self-Building Labs, arXiv:2610.23826v1](https://arxiv.org/html/2610.23826v1).
