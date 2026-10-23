# Academy 0.2.0 deployment and native acceptance blocker

The user explicitly authorized resources necessary to build the internal Flex AMI,
run one GPU EC2 in the existing development environment, deploy Academy 0.2.0 and
complete real browser video/refresh/reset/second-run acceptance on 2026-10-20.
This supersedes the earlier preparation-only restriction; future continuation does
not require repeating that resource authorization.

**2026-10-23 update:** the user deferred real-account acceptance. Do not resume
authenticated learner or native browser acceptance until the user resumes that work.
Image preparation and the bounded capacity trial remain authorized; keep no idle
acceptance host while waiting. The added US$400 account budget was canceled and
removed; the organization's existing budget was preserved.

## Completed live deployment

- Existing account: SDL0-DEV1 / `247893369214`, verified with STS after SSO refresh.
- Region: `ca-central-1`.
- Application: https://d2m3yolcjdy6d2.cloudfront.net
- Deployed implementation: `674c1e22808a0b4ad3cca09b90204f0a370ee74f` (Academy 0.2.0).
- Four application Lambda functions updated and exact CodeSha256 verified.
- 35 frontend files and `/version.json` match the tested release manifest.
- `/api/health` and `/api/config` return 200; learner, simulation and commissioning
  report endpoints deny unauthenticated requests with 401.
- Global remote execution remains false. No unqualified host is promoted.
- Signup Lambda, learner admission rules and existing infrastructure were unchanged.
- Previous four function archives and versioned index/version metadata are retained
  in the protected local commissioning artifact directory for rollback.

The actual public Onboarding welcome page was opened and rendered successfully.
This is deployment evidence, not authenticated learner or native execution evidence.

## Quota at the 2026-10-20 deployment

AWS reports **0 vCPU** for `Running On-Demand G and VT instances` (`L-DB2E81BA`)
in Canada Central. The same evaluated quota is zero in US East (N. Virginia);
Canada's G/VT Spot quota is also zero. No GPU instance exists in the Canadian account.

A minimal **16 vCPU** Canadian quota increase was submitted:

- Request ID: `03c9709eda424a1490b2f1451ef3feb3SWYBcdvl`
- Current request status: `CASE_OPENED`
- AWS support case: `179250244900163`

A pending request is not an approved quota. No Packer build, GPU host or AMI was
started while this quota remained zero. Actual video, refresh recovery, reset and
second native execution are all **not accepted**. No synthetic result substitutes.

## Current continuation path (2026-10-23)

The applied Canadian G/VT quota is now **8 vCPU**; the 16-vCPU request remains open.
Follow [GPU-CAPACITY-TRIAL.md](GPU-CAPACITY-TRIAL.md) with an explicit g6.2xlarge
selection. Revalidate AWS identity, applied quota, current caller SSH /32, base AMI,
input digests and credential lifetime before invoking the guarded build wrapper.
The build and deployed application must use the same reviewed source commit.

Use one GPU at a time. The current g6.2xlarge price snapshot is $1.08547 per
compute-hour; the two-hour build trial is about $2.17 compute, with IPv4, storage,
snapshots, media and traffic extra. The initial eight-hour operational target is
not an AWS billing cap. The accepted image may be retained without a running host.

After the user resumes account acceptance, enroll the pinned worker, then follow
[COMMISSIONING.md](COMMISSIONING.md) using a real authenticated browser. Preserve
receipts, reconcile unknown outcomes without replay, and drain/reset/release before
stopping the acceptance host. Keep image and evidence for the user's next session.

Machine-readable live checks: [deployment evidence](evidence/ec2-gpu/live-deployment-2026-10-20.json).
