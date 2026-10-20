# Academy 0.2.0 deployment and native acceptance blocker

The user explicitly authorized resources necessary to build the internal Flex AMI,
run one GPU EC2 in the existing development environment, deploy Academy 0.2.0 and
complete real browser video/refresh/reset/second-run acceptance on 2026-10-20.
This supersedes the earlier preparation-only restriction; future continuation does
not require repeating that resource authorization.

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

## External blocker

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

## Resume without redoing deployment

Recheck the exact quota request and applied quota first. Once the applied value is
at least 16, revalidate AWS identity, current caller SSH /32, base AMI availability,
input digests and fresh credentials. The protected build variables now bind the
existing platform VPC/public subnet and reviewed Canonical Ubuntu 24.04 base AMI;
both build/license opt-ins reflect the user's live-build authorization. Invoke the
guarded build wrapper from [GPU-IMAGE-BUILD.md](GPU-IMAGE-BUILD.md).

Use one GPU at a time: temporary g6.4xlarge build host, then acceptance host after
Packer has terminated its build instance. The refreshed public price snapshot is
$1.4692 per compute-hour, plus IPv4, EBS, snapshots, media, traffic and logs. Target
at most eight total GPU hours for the initial attempt (~$11.75 compute); this is an
operational target, not an AWS hard billing cap. A retained 300 GiB gp3 volume alone
costs $26.40/month at the captured price. Do not create idle resources while waiting.

Complete the installed image probes, enroll the pinned worker, then follow
[COMMISSIONING.md](COMMISSIONING.md) using a real authenticated browser. Preserve
receipts, reconcile unknown outcomes without replay, and drain/reset/release before
stopping the acceptance host. Keep image and evidence for the user's next session.

Machine-readable live checks: [deployment evidence](evidence/ec2-gpu/live-deployment-2026-10-20.json).
