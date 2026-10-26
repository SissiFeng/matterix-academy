# Supervised Flex connector installation

The companion includes a local installer adapter for the reviewed Flex deployment
hooks. **No installer recipe is currently approved.** The adapter refuses to
change a robot until the approved release catalog includes the exact
`installer_recipe_sha256`, runtime identity, artifact checksum and supported
firmware. Software tests exercise local Git/ZIP fixtures and intercepted
transports; they do not establish safe startup, CAN ownership, rollback, SiLA
transport or physical workflow acceptance on a robot.

Installing software, pairing a browser connection, qualifying the robot and
running a workflow remain separate operations. Installation never submits a
protocol. The [companion workflow](COMPANION.md) still requires an approved
profile, exact native Matterix proof and a local physical-motion confirmation.
OT-2 installation is blocked: its current upstream scripts do not provide the
equivalent transactional deployment and runtime identity contract. Windows
installation is also unavailable in this adapter.

## What the operator does

1. Connect the Mac or Linux computer to the lab network and obtain the robot's
   serial number, literal private IPv4 address, reviewed SSH host key and an
   authorized SSH private key. The adapter uses `root` with a dedicated key;
   password prompts, SSH agent forwarding and unverified host enrollment are
   disabled. Provisioning the initial SSH authorization remains a lab-admin step.
2. Obtain the approved artifact, qualified recipe and exact upstream Git commit.
   Obtain a private installer request containing the locally qualified robot
   profile. The recipe is shared across robots; the profile and SSH target are
   private per installation and are not incorporated in the shared recipe digest.
3. Launch **Install robot connector** in the companion launcher, or run the
   command below. The local terminal shows the exact serial, target, recipe and
   whether a new mutation credential is needed. Type `INSTALL` to approve that
   software installation and service-ownership change.
4. The adapter snapshots and verifies committed hooks, configs, archive bytes
   and SSH trust. It observes the robot's identity, current-run ownership and
   stock services. A fresh check occurs after confirmation and before each hook.
   A busy robot, changed release, unknown operation or retained deployment lock
   stops progress.
5. If the dedicated mutation credential is missing, the adapter creates a random
   secret locally in a private file and streams it over strict SSH stdin. The
   remote file is created atomically with mode 0600 and never overwrites an
   existing credential. Valid existing credentials are checked without returning
   their contents. Credential creation is journaled before the remote mutation.
6. The pinned deploy hook verifies and stages the runtime, performs import
   preflight and activates a versioned release. The pinned service hook then
   switches hardware service ownership. Postconditions require exclusive
   connector ownership, exact release pointers, current runtime identity,
   calibration, attached pipette and read-only SiLA identity checks.

The final receipt states whether installation completed. It explicitly records
`physical_workflow_executed: false`; use the separate Sim–Real workflow controls
for an approved experiment.

```sh
academy-bridge setup schema request
academy-bridge setup schema recipe
academy-bridge setup install \
  --request /absolute/private/flex-install-request.json \
  --recipe /absolute/private/approved-flex-recipe.json \
  --source-repo /absolute/path/to/opentrons-flex \
  --archive /absolute/private/approved-flex-runtime.zip
```

The source form is `python -m academy.companion.installer ...`. Packaged
`academy-bridge` uses its bundled Python for the exact reviewed local artifact
verifier and configuration hashing helper; no separate local Python installation
is required. Remote hooks retain their upstream robot Python/runtime requirements.

The request and recipe must be owned by the local user and mode 0600. The request
fields are `operation_id`, `installation_id`, `instrument`, `platform`,
`ssh_host`, `known_hosts`, `identity_file`, `robot_url`, `profile`, and optional
`sila_certificate_file`. Use a new operation UUID for a new explicit installation.
The HTTP address must identify the same IP as SSH on port 31950. The complete
profile schema is emitted by `setup schema request`; do not invent qualification
identities, calibration hashes, labware definitions or expiry dates to unblock
installation.

## Release qualification

The reviewed upstream Flex `main` commit was checked on 2026-10-24:
`c4c766a1f860109eaf7d72ce04c714697e34c244`. The adapter exports only the files
below from that committed Git object; a dirty working tree is not an input.
Matterix, its assets and the connector runtime remain independent repositories.

| File | SHA-256 |
| --- | --- |
| `deploy.sh` | `e8768034f498b8bd68f8552d6acfd51eb3cb3c1466550250afba9994a78a1f6b` |
| `scripts/artifact_manifest.py` | `ecfdb9fb1865c1ff78dea261c70c86896452710abb54f16805e036923ace1580` |
| `scripts/install.sh` | `de2877bcb3d360591134e388ee1bcddefa7ecb070855cbd908be1e8f36d0b275` |
| `scripts/install_connector_service.sh` | `e137ec4e9a29c35c1308647b06db467a615c9fac28f5e36ee32b8b9b8ef1d8ea` |
| `scripts/start_connector.sh` | `4d82dafe4e5a7fa694fac408b0b6ea1a4c7ed21172599201de194fe654205315` |
| `scripts/switch_mode.sh` | `bd6bedce2b58a1f3e58df19d2ca1fd0b956c09b2c83b1dbd190b06b5e7cf981d` |
| `scripts/rollback_connector.sh` | `6136df668e0d915235c7473c2831586c73a601166cdcd287a9592ae57f097f8c` |
| `config/flex_config.json` | `b2acfd723fc7bce9090e1bcd0a5dc05bb5ac78366b424dc299501cdabcd1396c` |
| `config/flex_unit_operations.json` | `c437ed48b384e70f4b8d3cfa034de66124c2c00224f238edf8981cd9a4ad6637` |
| `config/asms_unit_labware_movement.json` | `78e68e5e5d7374fcfe9716207d06aff68d048fbd5fa18a9698291af5be31a7de` |
| `config/asms_unit_operations.json` | `0ddcdbce79364e57bd4f70681654b640af3c4f3ddc4c406d0cd202ebfc5944ae` |

The recipe schema is `academy.flex-installer/1`. It binds this exact commit/file
map, the archive SHA-256, a qualification-report SHA-256, and three affirmative
qualification results: `no_motion_startup_verified`, `service_switch_verified`
and `rollback_verified`. These fields represent evidence the release operator
must collect; they are not a self-service approval mechanism. Only the catalog's
approved recipe digest authorizes the adapter to use them.

Qualification must verify the actual robot runtime against the upstream pinned
matrix (connector 0.9.1, Opentrons/robot-server 9.0.0, Python 3.12, aarch64 and the
reviewed Opentrons source commit); artifact verification is still performed by
the pinned upstream manifest helper. The approved catalog must also match
instrument, local platform, `opentrons-protocol-engine` transport, firmware,
source/artifact identity and the three runtime identity fields. Changing any
hook or config requires a newly reviewed adapter recipe and new evidence.

The release operator must test an idle robot, first installation, missing and
existing mutation credentials, loss of SSH output at each mutation, stock/connector
service transitions, and explicit rollback. Stock Opentrons does not share the
connector deployment lock: the lab must reserve the robot against concurrent
stock clients throughout installation. Repeated read-only idle checks do not
provide a distributed lock against another operator starting a stock run.

## Lost responses and recovery

Real setup holds the same local process lock as the normal companion for the
whole operation. Close the waiting/running companion before setup; unresolved
physical-workflow history must be reconciled first. Internal transport/hash
helpers do not acquire a second copy of that lock. This prevents local workflow
dispatch from racing a service switch; external stock clients still require the
lab reservation described above.

The production journal has one fixed location:
`~/.local/share/academy-companion/installer/`. It is private, process-locked and
uses durable SQLite transactions. Every remote mutation is recorded as attempted
before dispatch. A timeout, process interruption or failed postcondition is
`unknown`, even if the remote action may have succeeded. The same operation never
automatically repeats. A different operation ID cannot bypass an unresolved
journal entry. Keep this directory; do not delete its records to retry.

For an installation needing recovery, explicitly request:

```sh
academy-bridge setup rollback \
  --operation-id ORIGINAL_INSTALL_UUID \
  --rollback-id NEW_RECOVERY_UUID
```

After fresh identity, idle, trust and release-pointer checks, type `ROLLBACK`.
The adapter invokes the pinned previous-release hook only when the observed
previous/current pointers belong to that original installation. A completed
recovery cannot be repeated with a different UUID to toggle the global previous
release. Receipt and original resolution are committed atomically, retaining
the original unknown receipt.

On a first installation with no prior connector release, recovery can confirm
that stock services already own an idle robot without any mutation. If the new
connector owns the robot, the explicitly approved stock-mode hook restores stock
ownership. This retains installed software, mutation credentials and all evidence;
it is not an uninstall. Expired workflow qualification does not block identity-
checked software recovery. Active runs and retained upstream operation locks do
block it; the adapter never deletes a lock to force recovery.

If the rollback response itself is lost, it is also unknown and cannot be
replayed. An operator may perform a separate read-only reconciliation:

```sh
academy-bridge setup reconcile \
  --operation-id ORIGINAL_INSTALL_UUID \
  --recovery-id UNKNOWN_RECOVERY_UUID \
  --resolution-id NEW_RESOLUTION_UUID
```

Type `RECONCILE` after checking the local summary. The tool requires verified
stock ownership, an idle robot, the original identity/trust and release pointers
consistent with the recorded attempt or its rollback. It executes no installation
or service hook. Both historical receipts remain unchanged; a separate audit
resolves their locks atomically. If the robot is still running the connector,
its identity cannot be verified, or release pointers have changed independently,
reconciliation stops for lab-admin inspection.

## Software verification boundary

`tests/test_connector_installer.py` uses actual temporary Git repositories and
ZIP extraction plus intercepted SSH/hook processes. It covers catalog/recipe
pinning, dirty-source exclusion, strict SSH options, stdin-only credential
provisioning, persisted pre-mutation phases, identity and idle refresh, content
changes after confirmation, first-host recovery, release-pointer binding,
rollback idempotence, atomic audits, frozen CLI dispatch and read-only identity
requests. These tests do not execute robot deployment hooks or connect to lab
equipment. No AWS resources or physical instruments are modified by the suite.
