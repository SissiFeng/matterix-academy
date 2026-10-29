# Connect a local instrument from Academy

This feature adds **Sim → Real → Connect an instrument** and the same entry from
Workflow Studio. The interface is English. macOS is the first desktop delivery
platform. This checkout is a local implementation, not a deployed or qualified
physical system.

## What the path does

1. Save the instrument, deck layout and workflow in Studio.
2. Run that exact saved plan in a qualified Matterix environment. Review its native
   result and release/reset the DT session. A teaching animation or an Opentrons
   software simulation cannot satisfy this step.
3. Open **Connect an instrument**, select the model and register this computer.
4. Download the reviewed Mac companion when a notarized package has been published.
   Open it locally and use the lab-approved configuration. The browser cannot
   silently install software on a computer or on a robot.
5. Generate a single-use pairing code and enter it in the local companion. The
   code expires after ten minutes. Robot addresses, SSH keys, calibration and
   machine credentials remain local; Academy receives bound identity/status.
6. Check the connected serial, firmware, running connector, SiLA identity and
   calibration. The page reports missing prerequisites explicitly. Installation
   and connection checks do not authorize motion.
7. Review the exact saved plan and acknowledge physical motion in the browser.
   A qualified operator must also approve that specific plan on the connected
   computer. The companion submits one protocol to the connector-owned Opentrons
   Protocol Engine, reads its result, and returns a durable receipt.
8. Refresh to recover the same run. Stop requests target that run. Before another
   run, prepare new consumables, obtain current preflight and give new consent.

The connector owns the robot hardware. SiLA is used for identity and capability
checks; whole workflows use the connector's Protocol Engine HTTP interface. This
is not a claim that either connector exposes a generic SiLA workflow command.
The existing independent bridge informed the receipt and recovery design; its
runtime and local modifications have not been copied into Academy.

## Mac candidate build

The reproducible source entry is:

```sh
uv run --extra companion --with pyinstaller==6.16.0 python scripts/package-companion.py \
  --output build/companion-macos-candidate-NEW
```

Run on the target Mac architecture. It snapshots Academy source, embeds Python
and pinned dependencies, checks the executable's help entry, and writes a ZIP,
source fingerprint, per-file checksums and `build-result.json`. No system Python
installation is required to run that bundle; reviewed installer helper scripts use
the bundled Python too. The build verifies the actual binary with `doctor`,
including its pinned SiLA dependency metadata, without contacting an instrument. Open `Start Academy Bridge.command`
and provide the private lab configuration. The launcher offers pairing,
read-only inspection, supervised workflow waiting, the separate reviewed Flex installer, and an offline Mac runtime check. The installer is described in [INSTALLER.md](INSTALLER.md).

A local candidate is not Apple-notarized. Do not disable macOS security settings
to distribute it. Public download remains unavailable until a reviewed signed and
notarized package has passed installation acceptance and is represented by a
`CompanionPackage` in `companion_packages` in the deployed catalog. Distribution
is architecture-specific (`arm64` or `x86_64`). The catalog returns a five-minute
presigned download URL from the private bucket; private source code and AWS
credentials are not included in the bundle.

See [COMPANION.md](COMPANION.md) for local configuration, labware, calibration,
SiLA identity, credential storage and execution details. A new configuration must
be based on observed hardware; there is intentionally no fabricated qualified
profile to copy into production.

## AC source and private S3 delivery

The allowlisted sources are:

| Instrument | Repository | Observed source on 2026-10-24 | Qualification boundary |
| --- | --- | --- | --- |
| OT-2 | `AccelerationConsortium/opentrons-ot2` | `87e87f413bd608dfa18c369f2bfdbe97a365509c` / 0.5.0 | Build succeeded but tests failed; runtime identity and native DT qualification are missing. |
| Flex | `AccelerationConsortium/opentrons-flex` | `c4c766a1f860109eaf7d72ce04c714697e34c244` / 0.9.1 | Available ARM artifact was built from older `4d711a53330d27f79e3e2e3a308eb92cf21f0dfc`; it is not evidence for current main. |

These observations are recorded as candidates, not approved downloads. The
checked-in catalog contains **zero approved robot releases**. Current main and
upstream workflow status must be re-read before promotion.

```sh
uv run python scripts/connector-release.py inspect --output build/intake-NEW.json
```

The GitHub workflow `connector-sync.yml` runs scheduled intake only when
`CONNECTOR_SYNC_ENABLED=true`. Its six-hour intake records source commits,
builds, tests and artifact metadata. Manual intake remains available with an
empty manifest ID. **It does not auto-install new main or automatically promote
a candidate.** A manual publication selects an exact reviewed manifest from
`ops/connectors/releases/<manifest_id>.json` and verifies that artifact's build
directly, independently of scheduled intake. The protected publication environment
and its configured credentials are still required.
No fabricated approved manifest is included.

Configure the protected `connector-publication` environment with:

- `CONNECTOR_ARTIFACT_READ_TOKEN`: a dedicated, least-privilege credential that
  can read the required AC Actions artifacts. Do not reuse a personal browser
  session or put a token in a manifest.
- Variables `CONNECTOR_PUBLISH_ROLE_ARN`, `CONNECTOR_EXPECTED_ACCOUNT`,
  `CONNECTOR_ARTIFACT_BUCKET` and `CONNECTOR_AWS_REGION`.
- OIDC trust restricted to this repository and protected environment. Limit the
  publishing role to the reviewed bucket and `connectors/` prefix, plus the
  bucket checks and account identity read used by the publisher.

The destination must be an existing private, versioned bucket with all four
public-access blocks. The publisher refuses public and CloudFront web buckets,
wrong accounts, mutable overwrite, mismatched checksums, unrelated build IDs,
expired artifacts and missing source provenance. Approved packages must be
Actions artifacts tied to the exact passing source/build/test evidence and
observed rollback/no-motion qualification. A successful mirror uploads bytes and
a manifest only; it does not deploy or activate anything.

Local equivalents, using an actually reviewed manifest, are:

```sh
uv run python scripts/connector-release.py fetch \
  --manifest REVIEWED_MANIFEST.json --kind actions --artifact-id REVIEWED_ID \
  --output build/new-package.zip
uv run python scripts/connector-release.py verify \
  --manifest REVIEWED_MANIFEST.json --bundle build/new-package.zip
uv run python scripts/connector-release.py mirror \
  --manifest REVIEWED_MANIFEST.json --bundle build/new-package.zip \
  --bucket REVIEWED_PRIVATE_BUCKET --expected-account REVIEWED_ACCOUNT_ID \
  --confirm-publish
```

After publication, review and deploy the exact catalog update separately. At most
one active approved release exists per instrument, with an explicit platform
list. Upstream main changes never modify an active installation or physical run.

## Optional AWS deployment

Follow [AWS.md](../AWS.md), review the account and Terraform plan, and keep the
existing deployment boundary. This implementation did not apply Terraform or
write to S3. `infra/connectors.tf` defaults to no additional resources and no
physical execution.

- `connector_companion_enabled=true` creates a separate machine API/Lambda.
- `connector_artifact_bucket` grants the user API read access only to approved
  objects in the reviewed existing bucket.
- `connector_real_execution_enabled=true` is a separate global gate. It requires
  the companion API and still cannot bypass per-device qualification, current
  native proof, exact profile/plan identity or the local operator.

Browser requests use the existing API Gateway JWT-authorized user subject.
Machine requests use their own scoped credential on the dedicated endpoint;
Cognito/native-worker credentials are not repurposed. The companion API rejects
browser Origin headers, exposes no user data API, and is rate limited. Revocation
is checked on each request and after claim.

`build-lambda.sh` packages both handlers. Terraform manages the optional companion
Lambda code; the ordinary web/API release workflow does not update that optional
function by itself. Review the matching source/catalog update in its Terraform
plan as part of every companion release. Give the lab configuration the exact
`connector_companion_url` output; never infer it from the website origin.

## Qualification and unknown outcomes

`connector-qualify.py` records an operator's observed evidence; it does not itself
perform physical qualification. It requires a private profile/evidence file,
current exact approved release, fresh matching probe, expiry and expected
record version. It previews by default. Writing requires both `--apply` and
`--confirm-supervised-qualification`; DynamoDB also requires an explicit matching
`--expected-account`. No browser or machine endpoint grants qualification.

If a robot mutation times out or a process crashes, its outcome is `unknown`.
Neither refresh nor restarting Bridge retries the physical command. The device
remains locked pending inspection of the original robot run. Use
`connector-resolve.py --help` for the offline operator procedure. Its private
evidence must bind the exact command, installation, device, plan, connector and
robot IDs, confirm stopped/released state or that no run was created, and include
an evidence digest. The original unknown receipt remains unchanged. A resolution
allows a separately authorized **new** command; it never replays the old one.
A cloud Stop button is not an emergency stop.

## Acceptance before enabling a lab

Run and retain evidence separately for:

1. Local unit/API tests, Lambda build, Terraform/Packer validation and full browser
   journeys, including stale versions, isolation, replay denial and recovery.
2. Signed/notarized Mac installation, pairing, logout/revocation and permissions.
3. Approved artifact download, robot installation, process identity, SiLA wire,
   calibration, ownership handoff and rollback on the actual supported firmware.
4. Real Matterix execution of the same saved plan, reset/release and browser
   evidence recovery. A GPU capacity failure leaves this gate incomplete.
5. Supervised physical run with appropriate teaching liquids, verified commands,
   stop/recovery, refresh, consumable reset and a second distinct run.

Software HTTP fixtures and the Opentrons 9.0 simulator exercise real client code
and compiler behavior. They are not native Matterix or physical acceptance.
