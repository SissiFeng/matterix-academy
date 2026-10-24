# Connector validation — 2026-10-24

Status: local software implementation validated. This is not a cloud deployment,
approved desktop release, native Matterix qualification or physical robot acceptance.

## Executed checks

| Check | Observed result | Evidence boundary |
| --- | --- | --- |
| `bash scripts/verify.sh` | Passed; 1,219 Python tests, two dependency deprecation warnings | Includes lint, frontend build/format, Node commissioning checks and infrastructure validation |
| Full Playwright journeys | 69 passed | Real browser against local Academy; connector/robot services use controlled fixtures |
| `bash scripts/build-lambda.sh` | Passed | Python 3.12 Linux x86_64 API and Cognito admission packages built locally |
| Terraform validation and disabled EC2 plan | Passed; zero resources | No account selected and no apply |
| Packer schema check | Passed with fake inputs and cloud access blocked | No AMI build or GPU allocation |
| Opentrons 9.0 software simulator | Flex and OT-2 generated protocols completed | Pickup, 100 µL aspirate, dispense and drop; vendor software simulation only |
| Desktop/mobile review | English setup page inspected; responsive layout checked | No claim of Apple installation or hardware readiness |
| Independent implementation/security review | Reported concrete findings repaired and covered by tests | Local code review; not a penetration test or device certification |

The connector tests cover both persistence backends, owner isolation, atomic
single-use pairing, stale versions, token revocation, plan/native-result binding,
package provenance, firmware/profile mismatch, duplicate dispatch, uncertain
outcomes, operator reconciliation and append-only receipts. The local installer
tests cover strict transport policy, pinned source helpers, first-install and
rollback recovery, service ownership checks and shared execution/installation
locking. Installer effects are intercepted; no test controls a physical robot.

## Reproducible evidence

The executing worktree retains `build/connector-final-verify.log`,
`build/connector-final-lambda.log` and `build/connector-browser-release.log`.
The task's delivery folder retains copies alongside `opentrons-simulator.json`,
`ac-source-intake.json`, desktop/mobile screenshots and the separately generated
Mac package build report.

The Mac packaging script records its source commit, dirty status, source tree
hash, dependency inventory and archive SHA-256. It runs the frozen executable's
help and offline runtime doctor (including bundled gRPC metadata). The generated
report is evidence for that exact archive only. Packaging does not publish,
install, contact a robot or notarize the app.

## Remaining release and field gates

The checked-in release catalog intentionally contains no approved connector or
desktop artifact. Upstream intake found no complete, current approved source/build/
test combination for both instruments. Flex has a reviewed installer adapter;
OT-2 remains blocked until equivalent deployment and runtime identity contracts
are available. No qualified installer recipe is included.

Before publishing downloads, approve the exact connector artifact and recipe
against observed device evidence, sign/notarize the Mac package, configure the
private S3 publication identity and deploy the Academy control plane. Publication
is opt-in and cannot silently upgrade a connected robot.

Before physical execution, qualify the local profile and read-only SiLA identity,
complete actual Matterix native qualification for the exact saved plan, and run
a supervised commissioning procedure on the attached robot. Refresh recovery,
reset and a second physical run still require live acceptance. Synthetic Academy
results and Opentrons software simulation cannot satisfy these gates.
