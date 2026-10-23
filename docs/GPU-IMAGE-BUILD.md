# Internal Flex image and Academy source release

The source release is Academy **0.2.0**. `ops/ec2-gpu/academy-release.json` records
the initial immutable source release. For a reviewed update, export the exact tested
commit to a new protected directory and retain its generated `release.json` with
the reviewed build configuration. Do not overwrite an earlier release's inputs.
Source packaging alone does not deploy the application or qualify a GPU image.
No AWS account is selected by the preparation commands.

## Resolved runtime

The internal README's torch 2.10 / torchvision 0.25 instruction is incompatible
with the complete Isaac Sim 6.0.1.0 dependency graph: `isaacsim-core` requires
`torchvision==0.26.0`, which requires `torch==2.11.0`. The installable candidate is
therefore **torch 2.11.0+cu128 / torchvision 0.26.0+cu128**. Lab remains
`3.0.0b2.post1` and Sim remains `6.0.1.0`. Do not use `--no-deps` to force the old
inconsistent pair into the image. The locked installer uses `--no-deps` only after
resolving the entire 245-package closure, with every version and artifact hash fixed.

Two independent Python 3.12 environments prevent conflicting Pydantic requirements:

| Environment | Dependency authority | Purpose |
|---|---|---|
| `/opt/academy-agent/.venv` | `agent-requirements.lock`, exported from frozen Academy `uv.lock` | Outbound worker, API/media client; Pydantic 2.13.5 |
| `/opt/matterix-isaac` | `runtime-linux-x86_64.lock` | Native Kit/PhysX/renderer and independent Matterix source; Pydantic 2.11.10 (<2.12 required by Lab) |

The runtime lock targets CPython 3.12 / Linux x86_64 / glibc >=2.35, and includes
Matterix's psutil, toml, protobuf<5, tensorboard and scikit-learn requirements.
Ubuntu 24.04 meets the libc requirement. `flatdict` is source-only; its archive
hash and setuptools/wheel/packaging build tools are pinned. Runtime installation
uses those tools without a separate floating build environment. Upstream package
indexes are accessed only for the exact hash-locked artifacts.

The public NVIDIA 595.58.03 installer is pinned by its publisher's SHA256:
`8c0d4f967b7932c4ab5714272aee8103392b0a702c92afa555176d36205829f9`.
URL and checksum source are in `ops/ec2-gpu/image/driver.json`. Downloading it does
not install it or accept its licenses. The Packer build requires explicit license
acceptance. Keep that driver fixed until compatibility is retested.

The base Ubuntu AMI must be a reviewed, region-specific 24.04 x86_64 image with
SSM enabled and without an incompatible loaded display driver. Never use a latest
image lookup. OS prerequisites are listed in `image/ubuntu-packages.txt`; actual
kernel, installed dpkg versions and SSM version must be retained with the resulting
image. OS repositories are not a bit-for-bit snapshot: review any rebuild's OS
delta rather than claiming identical image bytes. Every build emits fresh inventories.

## Prepare inputs locally (no AWS)

Use a protected directory **outside all Academy, engine and asset checkouts**.
The source export never copies credentials, hooks, untracked files or external
submodule content; the engine's historical data submodule is deliberately replaced
by the separately pinned internal asset checkout via `MATTERIX_ASSETS_DATA_DIR`.

```sh
uv run python scripts/ec2-gpu-sources.py \
  --engine-root /path/to/Matterix-Internal-flex-pr \
  --assets-root /path/to/Matterix-assets-flex-pr \
  --output-dir /protected/academy-image-input
uv run python scripts/ec2-gpu-release.py \
  --revision REVIEWED_COMMITTED_FULL_SHA --output-dir /protected/academy-image-input
uv run python scripts/ec2-gpu-driver.py --download \
  --output-dir /protected/academy-image-input
```

Academy must be clean with the reviewed commit checked out at HEAD. The code release archive is deterministic and
secret-free. The internal repositories remain independent at reviewed commits
`18a96b78ee989fbf4e480e9db6a588c148c6adbe` and
`c57f12a04079a5f99405e1fcb818a3b7ccc52e5b`. Engine/assets archives are private.
Packer uploads only the eight named build inputs, never the whole protected folder.
Export sources first: the reviewed image manifest binds `sources.json` and therefore
both private archive hashes. Replacing an archive and its adjacent record together
must fail the manifest binding. Regenerate the reviewed release if the inputs change.
Before any build, check all payloads and source/release/driver bindings offline:

```sh
uv run python scripts/ec2-gpu-inputs.py --input-dir /protected/academy-image-input
```

The checker reports `inputs_ready_for_authorized_build`, while `image_built` and
`browser_dt_accepted` remain false. A failed checksum blocks the next step.

Use Packer **1.16.1** and Amazon plugin **1.8.3**:

```sh
packer init ops/ec2-gpu/image
packer fmt -check ops/ec2-gpu/image
packer validate -syntax-only ops/ec2-gpu/image
```

These preparation/validation steps create no cloud resources. The build has two
false-by-default requirements: explicit paid-build authorization and NVIDIA license
acceptance. It does not use or install any worker token.

## Build only after resource authorization

Copy `build.pkrvars.json.example` to the protected directory. Fill the authorized
account, exact base AMI, existing VPC/subnet, operator IPv4 `/32`, and input directory.
Use `archive_sha256` and `manifest_sha256` from `release.json`. Set both confirmation
flags true only once separately authorized. For the current 8-vCPU Canadian trial,
also set `"build_instance_type": "g6.2xlarge"`; see [capacity trial](GPU-CAPACITY-TRIAL.md).
Run the build against the same reviewed commit packaged in the protected `release.json`:

```sh
uv run python scripts/ec2-gpu-build.py check --config /protected/approved-build.pkrvars.json
uv run python scripts/ec2-gpu-build.py build --config /protected/approved-build.pkrvars.json \
  --confirm-paid-build --accept-nvidia-eula
```

The `build` command invokes Packer to create the explicitly selected single GPU instance
and 300 GiB encrypted gp3 disk, then retains an AMI/snapshot. The default g6.4xlarge
requires 16 vCPU; the current trial explicitly selects g6.2xlarge (8 vCPU).
This is a paid operation; source preparation does not run it.
The build wrapper checks the exact frozen credentials against the official regional
STS endpoint, rejects the wrong account, and passes only those verified credentials
to Packer. Always use this wrapper for builds; do not invoke `packer build` directly.
Temporary credentials must have a known expiry covering the build timeout, six
minutes of cleanup and two minutes of clock margin. The same frozen token is checked
again immediately before launch so slow capacity checks cannot consume that window.
The builder restricts temporary SSH to the operator's
single address, installs the pinned driver/runtime, reboots and performs final probes.
Root SSH provisioners are build-only. Learners use the existing browser API and
never receive SSH, SSM or worker credentials.

Finalization must pass the installed source/runtime fingerprint and instantiate the
fixed seed-42 Flex scene, produce three nonblack 960×540 native frames, reset and
close it. This scene/render probe does not execute or validate the mixing workflow.
It separately proves root IMDSv2 access succeeds while worker token requests fail
at the network layer. Missing SSM, source drift, dependency conflicts, missing
assets, wrong GPU/driver, black renderer or unreadable service files abort the build.
Code is read-only to the worker; state/cache remain private and writable. The service
is disabled, no token exists, and the worker remains unqualified in every image.

Retain `/etc/academy-native/evidence/` inventories and Packer's `packer-manifest.json`.
The AMI tags include `AcademyManifestSHA256` and `AcademyReleaseSHA256`. Feed the
produced AMI ID/owner and manifest hash into the separate default-disabled EC2 pilot
root; it must match those tags. No AMI ID is invented before a successful build.

## Start browser DT acceptance

After the image and pilot host are separately authorized, enroll that one worker,
install its protected token, configure the existing worker API origin and start the
service. Deploy the **same Academy release** to the API/frontend through the existing
release procedure; a local source release does not update a running AWS application.
Then follow [COMMISSIONING.md](COMMISSIONING.md) to grant one designated user two
fixed runs and run the actual browser acceptance harness. Keep the global learner
execution gate disabled throughout commissioning.

Ready-to-use evidence requires the real Onboarding browser to show decoded native
video, complete all five workflow steps, survive refresh without another submission,
reset/release, and repeat once. Local browser fixtures and a successful AMI build
cannot substitute for that acceptance. Qualification additionally requires isolation
and interruption/recovery review. Neither image preparation nor packaging records it.
