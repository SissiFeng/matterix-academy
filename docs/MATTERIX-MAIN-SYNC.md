# Keeping Academy aligned with internal Matterix main

Academy can discover new internal Matterix features automatically and propose a reviewable update. Discovery never changes the running GPU worker, approved source pins, teaching claims, or learner access. New native behavior becomes available only after an explicit Academy integration and the existing GPU/browser qualification process.

The lifecycle is **main snapshots → metadata candidate → adapter/course review → immutable image → native and browser qualification → controlled release**. Every candidate is unqualified. The existing English teaching exercises remain synthetic.

## What runs automatically

`.github/workflows/matterix-sync.yml` runs on Academy `main` every six hours, at minute 23 UTC, or through **Actions → Review Matterix main updates → Run workflow**. An optional `repository_dispatch` with type `matterix-main-updated` can request an earlier scan. Event payloads cannot select repositories, refs, commands, paths, or release settings. GitHub schedules can be delayed; the manual action is available for an immediate request. [GitHub event documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

The job is bounded to 20 minutes on a GitHub-hosted CPU runner. It has no AWS credentials, OIDC deployment permission, image-build step, or GPU launch step. It performs these operations:

1. Validate the trusted Academy policy and its current adapter fingerprint.
2. Fetch fixed `main` snapshots from `ac-rad/Matterix-Internal` and `ac-rad/Matterix_assets_internal` independently. Fetch each approved baseline SHA separately, because it may belong to a feature branch and be absent from main's history.
3. Read Git objects without checking out upstream files, running hooks, executing source code, installing upstream dependencies, downloading LFS payloads, or initializing submodules. A shallow snapshot comparison does not claim ancestry or release compatibility.
4. Compare source/tree hashes, discover declared features, identify removals and compatibility blockers, and map impacted surfaces to Academy adapters, English courses, UI coverage and required evidence.
5. Upload a metadata report, including when there are no upstream changes. When changes exist, create one immutable draft PR per candidate identity with only `ops/matterix-sync/candidate.json` and `docs/evidence/matterix-sync/latest.md`.

The candidate identity binds the source snapshots, policy, approved baseline, and Academy adapter evidence. Repeated identical observations reuse the candidate. An existing open **or closed** PR is not duplicated or reopened. A conflicting branch, unexpected extra change, changed evidence, stale Academy main, or denied access fails the publication. The publisher never force-pushes, overwrites a human branch, merges a PR, edits approved runtime pins, or marks a worker qualified.

## First-time operator setup

The credentials and activation variable are intentionally not configured by this implementation. Until they are configured, a run produces **`setup-required`**, with `upstream_checked: false` and `activation_allowed: false`. Disabled intake completes this setup check without accessing upstream; an explicitly enabled intake with missing credentials fails and preserves the setup report. Neither result is evidence of a successful upstream synchronization. The workflow does not fall back to a personal token or the operator's local login.

The respective repository administrators must configure two separate GitHub Apps:

1. Create the **Matterix read App** with repository **Contents: read only**. Install it for only `ac-rad/Matterix-Internal` and `ac-rad/Matterix_assets_internal`. It requires no write permission in the `ac-rad` organization. Organization approval may be required.
2. Create the **Academy publication App** with repository **Contents: read and write** and **Pull requests: read and write**. Install it only for `SissiFeng/matterix-academy`. No AWS account or role belongs to either App.
3. In the Academy repository's Actions configuration, set variables `MATTERIX_READ_APP_ID` and `ACADEMY_SYNC_APP_ID` to the respective App IDs. Set secrets `MATTERIX_READ_APP_PRIVATE_KEY` and `ACADEMY_SYNC_APP_PRIVATE_KEY` to their corresponding generated PEM private keys. Keep both keys out of repository files, reports and terminal output. All four values are required before enabled intake can run.
4. Set repository variable `MATTERIX_SYNC_ENABLED` to the exact string `true` when both installations and permissions are ready.
5. Run the workflow manually from `main`. Review the artifact and the draft PR, and confirm the ordinary Academy verification workflow runs on that PR. Missing access must fail rather than report a completed sync.

The workflow mints two short-lived installation tokens from the separate Apps: an upstream token restricted to the two internal repositories with **Contents: read**, and a publication token restricted to Academy with **Contents: write / Pull requests: write**. Tokens are revoked by the pinned action after the job. Source Git authentication exists only in the environment and an ephemeral askpass helper; credentials are not written into Git remotes or Git configuration. The publisher verifies that its token is an installation token scoped to exactly Academy. [Pinned GitHub App token action](https://github.com/actions/create-github-app-token/tree/64ab729a6294000f5aa4a4bc0b73d1f32bc45510).

Using an App token permits normal PR CI to start without the automation restrictions of `GITHUB_TOKEN`. [GitHub workflow trigger documentation](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow#triggering-a-workflow-from-a-workflow).

To disable intake, set `MATTERIX_SYNC_ENABLED` to `false` or remove it. This changes neither the currently deployed Academy release nor existing qualified workers. Removing either App secret also prevents upstream access. No new monthly AWS budget or alert is created.

## Feature synchronization is an integration task

Main is a development branch, not a qualification certificate. The inspected main snapshots can differ from, or omit features present in, the approved Flex branch. The independent assets main can also be behind the approved asset snapshot. Required scene files missing from either candidate must block promotion even if the scan itself completed successfully.

The current native adapter compiles a fixed 86-action Flex workflow for its approved scene. Discovery of another task, action, device, asset or observation does not make it executable from the browser. The report identifies affected integration surfaces; it cannot generate a correct lesson, prove physical semantics, or infer a compatible engine/assets pairing.

For each feature selected for release, the integration PR must include:

- An explicit supported/unsupported decision, with required device, asset, observation and runtime compatibility.
- A constrained native adapter and versioned recipe, including state transitions, failure paths, immutable run identity, stale-version rejection and recovery behavior.
- An English course and browser entry point with suitable explanations and evidence labels. Teaching results retain the synthetic boundary. A new native capability is exposed only for its qualified recipe/scene.
- Tests for the changed behavior and a coverage/evidence record linking the feature to its exact candidate and release. Unsupported discoveries remain visible in the review report rather than being silently advertised as available.

Review both repository commits together. The tool does not assume simultaneous main updates are paired, modify either upstream repository, or copy Matterix runtime, binaries, scenes or assets into Academy. Candidate files contain metadata and hashes, not imported source code or LFS asset payloads.

## Promotion and rollback

The candidate PR is only an intake record. Merging it can trigger the existing deployment of current approved Academy application code, because every Academy main update is deployed; it does not change the native image, source pins or qualification. Native promotion remains a separate reviewed change using [the image manifest and compatibility procedure](GPU-IMAGE-BUILD.md), [GPU deployment procedure](EC2-GPU-PILOT.md), [worker controls](WORKER-CONTROL.md), [integration contract](MATTERIX-CONTRACT.md), and [AWS deployment procedure](AWS.md).

For an incompatible adapter, recipe or runtime-profile change, use a maintenance
window: stop new allocations, finish and reconcile existing runs, and disable the
remote entry point **before** merging the integration change into Academy main.
Keep the protected deployment expectation aligned with the reviewed remote flag.
Commission the replacement through the bounded commissioning grant, then reopen
the qualified capability. The current single-profile adapter is not a rolling
upgrade controller; an uninterrupted upgrade would first require explicit support
for both recipe/runtime versions. Stored runs retain their original identities.

1. Review source pairing, feature coverage, supported Ubuntu/Isaac/Isaac Lab/Python/driver versions, and both native and worker dependency locks. Update the runtime profile and image manifest together in the integration change; preserve prior release inputs.
2. Run `bash scripts/build-lambda.sh`, `bash scripts/verify.sh`, and the Playwright journeys. Passing local or CI tests does not qualify a GPU image or a real learner account.
3. Export the exact independent engine/assets sources first, then package the matching Academy commit and build an immutable AMI using the existing bounded build wrapper. A scan never authorizes or initiates paid builds. Use the existing account/cost controls and explicit paid-build authorization for this separate operation.
4. Register a **new worker identity** for the new image and source/runtime fingerprint. Never reuse a previous worker's qualification for a new source pair. Collect the image probe, native run, isolation, capacity and interruption evidence against that identity.
5. Complete authenticated browser acceptance: real video bound to the same native session/run, refresh recovery without duplicate execution, reset, and a second successful run. Keep the remote entry point unavailable while any required gate is missing or blocked.
6. Drain the previous worker so no new run is allocated to it; allow active runs to finish and reconcile uncertain outcomes. Switch only to the explicitly qualified release through the existing worker administration/deployment procedure. Do not mutate a live worker's source tree or pull main during an active session.

Rollback uses the retained prior AMI, matching Academy release/source pins and its evidence. Drain the candidate worker, reconcile its active runs, and restore the previous known-compatible release using the existing release procedure. A recreated host must satisfy the worker identity/fingerprint requirements; an old qualification record is never a substitute for a newly created worker's evidence. Do not delete the previous image or artifacts until rollback is no longer required.

GPU capacity and real-account acceptance remain independent operational gates. A completed candidate scan, a green metadata PR, or an image build does not mean a browser DT workflow is usable.

## Local inspection and recovery

With the two source repositories available locally and their `refs/remotes/origin/main` snapshots fetched, run from Academy:

```sh
python3 scripts/matterix-sync.py check-policy
python3 scripts/matterix-sync.py scan \
  --engine-root /path/to/Matterix-Internal \
  --assets-root /path/to/Matterix_assets_internal \
  --output-dir build/matterix-sync
python3 scripts/matterix-sync.py check \
  --candidate build/matterix-sync/candidate.json \
  --report build/matterix-sync/report.md
```

These commands are read-only with respect to the source repositories and do not require AWS access. For a missing approved baseline object, fetch that exact SHA from the corresponding fixed upstream before scanning. Do not substitute another baseline merely to obtain a passing report.

If publication fails after creating Git objects, a branch, or a PR, inspect the original run and reconcile the immutable `automation/matterix-<candidate-id-prefix>` branch before retrying. The next run reads and verifies existing state; it will not replay an uncertain overwrite. A moved Academy main requires a new scan from current trusted main. If a human edited the candidate branch, preserve it and resolve the conflict explicitly; the publisher refuses to repair it by force.

Artifacts are retained for 14 days. Candidate PR files provide the longer-lived metadata record; release inputs and qualification evidence continue to use the existing protected release storage. Never include private keys, access tokens, learner data, raw internal source or asset payloads in a report.
