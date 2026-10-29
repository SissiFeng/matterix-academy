# AC GPU blueprint and the Matterix worker

Source audit: 2026-10-26. AC's application blueprint supports GPU workloads through
ECS on EC2. Academy retains its dedicated Ubuntu GPU worker because the existing
image, worker protocol and commissioning tools already target that deployment.
The student web/API stack does not need to move to ECS.

## Verified configuration

The following inputs belong to AC's `react-python-fullstack` and `python-backend`
modules. They are **not inputs to Academy's Terraform stack**, and this example is
not a complete Matterix deployment:

```hcl
gpu               = 1
gpu_instance_type = "g6.2xlarge"
gpu_use_spot      = false
```

The instance choice above matches Academy's bounded trial; the AC module defaults
are `gpu = 0`, `g4dn.xlarge` and Spot enabled. A positive GPU count makes the ECS
task require EC2, requests GPU devices for the container and creates an EC2 Auto
Scaling Group with a GPU capacity provider. It does not bypass EC2 quotas or
instance capacity constraints.

The application inputs and their wiring were checked at
`infrastructure-modules@9a6f82de8763745de16e6e86050f4721b90886bb`:

- [Fullstack inputs](https://github.com/AccelerationConsortium/infrastructure-modules/blob/9a6f82de8763745de16e6e86050f4721b90886bb/modules/specialized/react-python-fullstack/variables.tf#L348-L375)
  and [forwarding to ECS](https://github.com/AccelerationConsortium/infrastructure-modules/blob/9a6f82de8763745de16e6e86050f4721b90886bb/modules/specialized/react-python-fullstack/main.tf#L48-L87).
- [Python backend inputs](https://github.com/AccelerationConsortium/infrastructure-modules/blob/9a6f82de8763745de16e6e86050f4721b90886bb/modules/specialized/python-backend/variables.tf#L217-L239).
- [ECS GPU device request](https://github.com/AccelerationConsortium/infrastructure-modules/blob/9a6f82de8763745de16e6e86050f4721b90886bb/modules/generic/ecs-service/main.tf#L221-L227),
  [service placement](https://github.com/AccelerationConsortium/infrastructure-modules/blob/9a6f82de8763745de16e6e86050f4721b90886bb/modules/generic/ecs-service/main.tf#L251-L265)
  and [EC2 capacity](https://github.com/AccelerationConsortium/infrastructure-modules/blob/9a6f82de8763745de16e6e86050f4721b90886bb/modules/generic/ecs-gpu-capacity-provider/main.tf#L1-L95).

The specific example URL
`AccelerationConsortium/cell_counting_images_aws/blob/dev/platform/vars/dev.tfvars`
returned HTTP 404 through the authenticated GitHub API. That can mean missing
access or a missing repository. The user subsequently supplied the SDL6 tfvars
contents directly on 2026-10-26. This verifies the supplied configuration, not
the inaccessible repository's current commit or SDL6's live deployment.

That file configures `sdl6-cell-count` in `dev`: one GPU, `g4dn.xlarge`, On-Demand,
2048 task CPU units, 14336 MiB task memory and RF-DETR/SAM2 inference. It requests
one ECS task with scaling up to four, private S3 storage, shared Aurora, built-in
authentication, SES, WAF and the `vibecount.online` domain. Its ACM certificate ARN
names account `687159379570`; this identifies the account written in the file,
not the current console session or a verified live SDL6 distribution.

Academy's verified development deployment is in account `247893369214`
(SDL0-DEV1), with CloudFront distribution `E3UW98EHZSA0FU` at
`d2m3yolcjdy6d2.cloudfront.net`. Its dedicated native trial uses `g4dn.2xlarge`
with 8 vCPU and 32 GiB host memory for pinned Ubuntu, Isaac and internal Matterix.
The supplied application's smaller inference host and ECS task settings do not
meet that host profile. Both use a T4 GPU, whose suitability for Academy still
depends on the native image and browser acceptance gates.

Academy follows AC's CloudFront identification convention: `comment = local.name`
and a `Name = local.name` tag, where `local.name` is `matterix-academy-dev` in this
environment. The existing `Application`, `Environment` and `ManagedBy` tags
already match AC's convention. See the pinned
[CloudFront naming](https://github.com/AccelerationConsortium/infrastructure-modules/blob/9a6f82de8763745de16e6e86050f4721b90886bb/modules/generic/cloudfront/main.tf#L1-L8)
and [Name tag](https://github.com/AccelerationConsortium/infrastructure-modules/blob/9a6f82de8763745de16e6e86050f4721b90886bb/modules/generic/cloudfront/main.tf#L171-L176).
This metadata alignment preserves the existing distribution and application.
Do not copy SDL6's `enable_cognito = false`, database, email, certificate or
domain settings into Academy: its API relies on Cognito JWT identity, and those
resources belong to the supplied application's configuration.

The accessible [core dev configuration](https://github.com/AccelerationConsortium/core-infrastructure/blob/521f4c0462e750f1e47886abe88f0228a704c166/platform/vars/dev.tfvars)
and [fullstack template dev configuration](https://github.com/AccelerationConsortium/platform-templates/blob/085e6aa59b57bd33e5a728f984b1db7036c620f3/unified-react-backend-app/platform/vars/dev.tfvars)
contain no GPU settings. The core repository has `main`, `test` and `prod`
branches; its workflow maps `main` to the `dev` environment. Its shared budget
configuration is outside Academy's deployment scope.

## Why this is not a ready-made Matterix deployment

| Concern | Verified AC module behavior | Implication for Academy |
|---|---|---|
| Host/runtime | Defaults to the Amazon Linux 2 ECS GPU AMI. User data only configures the ECS cluster and GPU support. | Academy's pinned Ubuntu/Isaac image and worker services still need installation and qualification. |
| Custom AMI | `gpu_ami_id` is exposed by the fullstack and generic ECS modules, but not the Python backend or foundation modules. | Substituting an Ubuntu AMI alone does not install an ECS agent or package the native runtime as a working container. |
| Storage | The launch template exposes no root-disk size or custom bootstrap. The task declares no persistent journal/cache volumes. | Isaac storage and durable worker recovery require explicit integration. |
| Host count | The application module hardcodes GPU ASG maximum size to two; service updates allow 200% tasks and require 100% healthy tasks. | `desired_count = 1` does not enforce the single-host cost limit and can require a second GPU during an update. |
| Resource ownership | GPU ASG, capacity-provider and IAM names derive from the shared cluster name. Both foundation and the GPU module manage the cluster capacity-provider list. | Enabling GPU in multiple application states can collide or overwrite shared cluster configuration. |
| Existing pool | The generic module declares `capacity_provider_name` but does not use it. | A tfvars value cannot currently select an existing shared GPU pool. |
| Network | GPU hosts have no public IP and use the supplied subnets. | Confirm outbound worker, artifact, SSM and media-relay access in the existing approved network. |

The [application ASG settings](https://github.com/AccelerationConsortium/infrastructure-modules/blob/9a6f82de8763745de16e6e86050f4721b90886bb/modules/generic/ecs-service/main.tf#L367-L383)
and [foundation capacity-provider ownership](https://github.com/AccelerationConsortium/infrastructure-modules/blob/9a6f82de8763745de16e6e86050f4721b90886bb/modules/foundation/components/ecs-cluster/main.tf#L36-L67)
are important review points before adopting that topology. The GPU provider's own
cluster attachment includes `FARGATE` but omits the foundation's `FARGATE_SPOT`;
both resources must not independently own the same cluster setting.

## Deployment decision and acceptance

Keep Academy's CloudFront/API Gateway/Lambda control plane and attach one dedicated
Ubuntu GPU worker through the existing outbound worker protocol. Follow
[AWS.md](AWS.md), [GPU-IMAGE-BUILD.md](GPU-IMAGE-BUILD.md) and the guarded
[GPU capacity trial](GPU-CAPACITY-TRIAL.md). Confirm the authorized account and
current capacity before a paid attempt; retain the exact Academy, internal
Matterix, assets, Isaac and AMI versions with its evidence.

If ECS becomes a deployment requirement, first resolve capacity-provider ownership,
expose a strict one-host limit and add a tested runtime/container, persistent worker
state and the required permissions. Pin the reviewed module commit instead of
following its floating `main` reference. That work can remain a separate worker
deployment without migrating the student application.

This audit records source capability, not a completed image build or native run.
A successful EC2 launch or render probe does not qualify the worker. Keep the live
DT gate closed until [MATTERIX-CONTRACT.md](MATTERIX-CONTRACT.md) and
[STUDIO-NATIVE-ACCEPTANCE.md](STUDIO-NATIVE-ACCEPTANCE.md) pass: the saved design must
run in internal Matterix with real browser video, refresh recovery, verified reset
and a second changed workflow. Synthetic teaching and physical execution retain
their separate evidence boundaries.
