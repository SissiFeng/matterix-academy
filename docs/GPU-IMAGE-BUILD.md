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
resolving the entire 247-package closure, with every version and artifact hash fixed.

Two independent Python 3.12 environments prevent conflicting Pydantic requirements:

| Environment | Dependency authority | Purpose |
|---|---|---|
| `/opt/academy-agent/.venv` | `agent-requirements.lock`, exported from frozen Academy `uv.lock` | Outbound worker, API/media client; Pydantic 2.13.5 |
| `/opt/matterix-isaac` | `runtime-linux-x86_64.lock` | Native Kit/PhysX/renderer and independent Matterix source; Pydantic 2.11.10 (<2.12 required by Lab) |

The runtime lock targets CPython 3.12 / Linux x86_64 / glibc >=2.35, and includes
Matterix's psutil, toml, protobuf<5, tensorboard and scikit-learn requirements.
It also pins HTTPX 0.28.1 and its HTTP Core dependency: native Studio loads the
Academy configuration/worker imports inside this environment, independently of
the agent environment. The offline import regression rejects packages absent
from the native lock; it does not substitute for GPU execution.
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
SSM enabled. Before any private payload upload, `prepare-gpu.sh` installs the
Nouveau blacklist and updates initramfs; if Nouveau is loaded it reboots. Packer
allows that disconnect, waits 30 seconds and retries the next shell connection for
up to ten minutes. Provisioning rejects a still-loaded Nouveau module before
extracting payloads and again before installing the pinned NVIDIA driver. It never
tries to unload a live driver. A failed initramfs update aborts before reboot.
Never use a latest image lookup. OS prerequisites are listed in `image/ubuntu-packages.txt`; actual
kernel, installed dpkg versions and SSM version must be retained with the resulting
image. OS repositories are not a bit-for-bit snapshot: review any rebuild's OS
delta rather than claiming identical image bytes. Every build emits fresh inventories.

## Prepare inputs locally (no AWS)

Native launchers disable Kit's process-terminating fast shutdown so probe callers
can save results and propagate failures. Graceful Kit teardown has a 60-second
watchdog; a timeout exits unsuccessfully and cannot qualify the image. Scene
failures retain a negative report and traceback before teardown.

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

Necessary paid build and single-host commissioning resources are already authorized
for the existing development account; the user resumed real DT delivery on
2026-10-26. Keep the explicit build/license flags and account checks. This
authorization does not imply a successful image or native browser acceptance.

Copy `build.pkrvars.json.example` to the protected directory. Fill the authorized
account, exact base AMI, existing VPC/subnet, operator IPv4 `/32`, and input directory.
Use `archive_sha256` and `manifest_sha256` from `release.json`. Set both confirmation
flags true only once authorized. The current 8-vCPU Canadian fallbacks are
`"build_instance_type": "g5.2xlarge"` and, after its capacity failures, the
user-authorized `"build_instance_type": "g4dn.2xlarge"`; `g6.2xlarge` remains
eligible. The T4 experiment requires 16,384 MiB physical GPU memory from EC2 and
at least 15,360 MiB visible after driver installation. A10G/L4/L40S retain the
22,000 MiB minimum. See [capacity trial](GPU-CAPACITY-TRIAL.md) for the pinned
PyTorch/driver/Turing compatibility evidence. No selection bypasses native probes.
Run the build against the same reviewed commit packaged in the protected `release.json`:

```sh
uv run python scripts/ec2-gpu-build.py check --config /protected/approved-build.pkrvars.json
uv run python scripts/ec2-gpu-build.py build --config /protected/approved-build.pkrvars.json \
  --confirm-paid-build --accept-nvidia-eula
```

The `build` command invokes Packer to create the explicitly selected single GPU instance
and 300 GiB encrypted gp3 disk, then retains an AMI/snapshot. The default g6.4xlarge
requires 16 vCPU; the current trial explicitly selects g4dn.2xlarge, g5.2xlarge or
g6.2xlarge (8 vCPU). Canadian G4 compute is USD 0.835/hour as checked on 2026-10-26;
storage, IPv4 and artifacts are additional.
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

Finalization must pass the installed source/runtime fingerprint, then run two
native probes in sequence:

1. Load the fixed seed-42 Flex scene, render at least three nonblack 960×540 frames,
   reset and close. This probe does not execute the five-step mixing workflow.
2. Construct the saved Flex Studio plan, execute pickup → aspirate 100 µL → dispense
   100 µL into A1 → drop, verify native observations and bound renderer frames,
   then reset and close. A failed terminal snapshot or reset fails the probe.

Both probes share one 30-minute timeout plus a 30-second termination grace and one
RSS/VRAM/OOM measurement window. Retain `scene-render.json`, `studio-probe.json`,
`capacity.json`, the raw measurement logs and the Studio run artifacts referenced
by its report. These are local GPU checks, not browser/media qualification. See
[capacity trial](GPU-CAPACITY-TRIAL.md) for the failure and retention rules.
Keep `balanced` rendering and 960×540 output for every candidate. The T4 trial
must not introduce frame generation or lower workflow, render, OOM or reset gates.

Finalization also proves root IMDSv2 access succeeds while worker token requests fail
at the network layer. Missing SSM, source drift, dependency conflicts, missing
assets, wrong GPU/driver, black renderer or unreadable service files abort the build.
Code is read-only to the worker; state/cache remain private and writable. The service
is disabled, no token exists, and the worker remains unqualified in every image.
All three native launch paths use Kit's explicit
[`--portable-root`](https://docs.omniverse.nvidia.com/kit/docs/kit-manual/latest/guide/configuring.html#portable-mode) under
`/var/cache/academy-native/academy-kit`; `HOME` alone cannot override the installed
Kit portable configuration. Before importing Isaac, the launcher checks the private
cache's ownership, path and actual writability. After startup it verifies Kit's
cache/data/log tokens remain inside that directory and emits `ACADEMY_KIT_PATHS`.
Finalization also uses the worker cache as its working directory, rather than the
builder's private home. No installed runtime or source directory becomes writable.

Retain `/etc/academy-native/evidence/` inventories and Packer's `packer-manifest.json`.
The AMI tags include `AcademyManifestSHA256` and `AcademyReleaseSHA256`. Feed the
produced AMI ID/owner and manifest hash into the separate default-disabled EC2 pilot
root; it must match those tags. No AMI ID is invented before a successful build.

## Start browser DT acceptance

After a successful reviewed image build and pilot-host deployment, enroll that one worker,
install its protected token, configure the existing worker API origin and start the
service. Deploy the **same Academy release** to the API/frontend through the existing
release procedure; a local source release does not update a running AWS application.
For saved workflows, follow [Studio native acceptance](STUDIO-NATIVE-ACCEPTANCE.md):
grant one designated user exactly two approved designs and run
`npm run commissioning:studio`. The second design changes both tip-rack placement
and transfer volume. [COMMISSIONING.md](COMMISSIONING.md) and
`npm run commissioning:live` cover the separate fixed mixing scene. Keep the global
learner execution gate disabled throughout commissioning.

Ready-to-use evidence requires the real Onboarding browser to show decoded native
video for the exact saved design, complete every approved action, survive refresh
without another submission, reset/release, and run the second approved design.
Local browser fixtures and a successful AMI build
cannot substitute for that acceptance. Qualification additionally requires isolation
and interruption/recovery review. Neither image preparation nor packaging records it.
