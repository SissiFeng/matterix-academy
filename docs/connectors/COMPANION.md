# Local connector companion

Status: implemented and tested against software HTTP fixtures. This is not a
hardware-qualified installer, a completed SiLA integration test, or an observed
physical run. No production profile is included and there is no default hardware
authority. The operator must qualify the actual connected robot, connector build,
pipette, labware and calibration before running.

The companion is an outbound Python 3.12 process on the computer attached to the
instrument. It opens no local web server and accepts no browser-supplied robot
address. This first release supports macOS and Linux private POSIX directories
and process locks. A native Windows installer, ACL implementation, service
lifecycle and signed distributions remain separate platform work; Windows must
not bypass the permission checks. The native Mac bundle includes Python and dependencies. The `pair`, `probe` and
`run` commands do not install the robot's SiLA server or take over an existing
robot controller; the separate locally confirmed `setup` flow is described below. The `companion` package extra supplies
the pinned grpcio 1.81.1 read-only SiLA client dependency; absence or a different
version blocks physical qualification.

## Installation and pairing

An administrator supplies a private `local-config.json` (mode 0600) with:

- `academy_url`: exact HTTPS API origin, also in local
  `allowed_academy_origins`; redirects and proxy-environment inheritance are off.
- `robot_url`: the connector-owned Protocol Engine origin at a literal private,
  link-local or loopback IP. The lab administrator selects this address locally.
- `loopback_development`: false for production. Only an explicit true permits
  loopback HTTP Academy fixtures.
- `profile`: a validated `RobotProfile` as described below. No example with
  fabricated physical qualifications is shipped as an installable profile.

The Python model can emit the exact JSON schema for local administration:

```sh
python -c 'import json; from academy.companion.config import LocalConfig; print(json.dumps(LocalConfig.model_json_schema(), indent=2))'
```

Use the installed package's Python interpreter:

```sh
python -m academy.companion pair --config /absolute/private/local-config.json
python -m academy.companion probe --config /absolute/private/local-config.json
python -m academy.companion run --config /absolute/private/local-config.json
```

`pair` requests the short-lived Academy code with a concealed terminal input.
For a reviewed desktop installer it can read `--code-file` from a user-owned 0600
file; it never accepts a pairing code or machine token as a command argument.
The generated random installation ID and secret are written before the pairing
request. If the response is lost, rerunning pair checks `/companion/me` with the
same credential before attempting pairing; it does not generate another secret.
Credentials stay under `~/.local/share/academy-companion`, mode 0700, with files
mode 0600. The optional global `--state-dir` must precede the subcommand.

After an installation is revoked, explicitly pair a new installation with
`pair --config /absolute/private/local-config.json --rotate-credentials`.
The companion first confirms that the old credentials are rejected, refuses
rotation while commands or receipts remain unresolved, and archives the old
private credential file before replacing it. A timeout during the identity check
does not permit rotation. For a lost pairing response, use ordinary `pair`
without this flag so the original credential is reconciled.

Pairing does not qualify hardware. `probe` reads `/health`, `/pipettes`, `/unitelabs/runtime`,
`/calibration/status`, `/calibration/pipette_offset`,
`/calibration/tip_length` and `/labwareOffsets` using `Opentrons-Version: 3`. It also
reads exactly three SiLA properties: ServerUUID, ImplementedFeatures, and
MotionController.IsSimulating. It checks exact running release, identity, versions,
calibration/offset fingerprint and SiLA feature identity, rejects simulated SiLA,
and reports the bound release/profile fingerprint to Academy. It never homes, moves, resets,
loads a protocol or calls a physical SiLA command.

## Qualification profile

A local administrator must record and inspect all of:

1. Qualification ID, responsible operator and expiry (`qualified_until`).
2. Instrument (`flex` or `ot2`), robot serial, exact connector source commit,
   approved release ID/artifact SHA256, firmware and HTTP API version. Also
   include `runtime_contract_id`, `runtime_release_id`, `runtime_bundle_sha256`
   and `connector_version` observed from the running connector process. The
   approved catalog binds the three runtime identity fields to source/artifact.
   Stock robot HTTP without the connector identity endpoint is rejected.
3. Actual pipette model, serial, mount and qualified minimum/maximum volumes.
   Only explicitly listed single-channel Flex and OT-2 models are accepted;
   unsupported models, multichannel instruments and arbitrary motor mechanics
   are rejected.
4. Full approved tip-rack, stock and plate labware definitions, canonical JSON
   SHA256, namespace, load name, version and physical slots. SHA256 is over sorted
   compact JSON (the companion's `digest` function), not arbitrary file whitespace.
5. Fresh-tip well positions, stock well, and capacities for stock/A1/A2/A3.
   Capacities cannot exceed the approved definition. Calibration/deck assertions
   must explicitly be true.
6. Canonical `calibration_sha256` over `{"calibration": GET_CALIBRATION_STATUS,
   "labware_offsets": GET_LABWARE_OFFSETS, "pipette_offsets": GET_PIPETTE_OFFSETS,
   "tip_lengths": GET_TIP_LENGTHS}`. Deck status must be `OK` and no
   calibration record may be marked bad. Any calibration/offset change invalidates
   qualification. This initial adapter submits no custom run offsets; decks needing
   nonzero per-run correction remain unsupported until offset execution is qualified.
7. `sila_server_uuid`, `sila_features_sha256` over `{"features": SORTED_FEATURE_IDENTIFIERS}`,
   local `sila_port`, and `sila_tls`. TLS requires a local private
   `sila_certificate_file` whose bytes match `sila_certificate_sha256`. Plaintext
   SiLA is allowed only when explicitly recorded in the local qualified profile
   on the physically attached private network. No discovery or arbitrary RPC runs.

The profile SHA256 includes the complete profile and expiry. Replacing any
component requires new local inspection and server qualification. A self-written
profile is not scientific or hardware acceptance evidence. The exact approved
artifact must first be verified and installed through its reviewed platform
procedure; a field typed into JSON is not cryptographic proof of a running
connector build. The current read-only SiLA identity client is implemented, but live SiLA
wire compatibility still needs independent observed acceptance. The current OT-2
connector lacks the required process-bound runtime identity endpoint; it therefore
fails closed even though its static compiler passes the optional vendor simulator.

## Execution and evidence

The server sends a saved Studio plan bound to the installation, instrument serial,
release, source commit, firmware, profile and plan hashes. It must independently
require the corresponding actual Matterix result and subject authorization.
Synthetic teaching never unlocks hardware. Current native Matterix acceptance
supports Flex only; an OT-2 compiler is not an OT-2 DT qualification.

The local compiler accepts only pickup, aspirate, dispense and drop. It checks
saved slots, a liquid ledger, pipette and destination capacity, fresh tips and an
empty pipette at completion. It emits a fixed Protocol API 2.20 template with all
data escaped into a JSON string literal. No arbitrary Python, raw coordinates,
SSH commands, calibration substitutions or generic OT-2 motor mechanics come
from Academy. Flex uses the qualified fixed waste chute; OT-2 uses fixed trash.

For each newly claimed run, a foreground terminal shows the robot model/serial,
full saved workflow, deck and hash. The local operator must type a phrase bound
to that serial and plan. Approval is never remembered for the next run. The
operator verifies prepared liquids, fresh tips, calibration and a clear workspace.
While waiting in the foreground, the companion repeats the full verified
read-only probe at most every 120 seconds, before the server's 300-second probe
expiry. It reports a fresh probe only after all local identity/calibration/SiLA
checks pass. A failed refresh stops dispatch; an old timestamp is never simply
renewed. For idle ownership, the bounded latest-run list and the robot API's
global `links.current` must both show no owner. Historical counts above 100
do not block a robot whose authoritative current-run link is explicitly null.

The companion then re-probes identity and idle ownership, uploads the generated
protocol, waits for successful analysis, creates one bound run, and submits play
once. It reads that run and its ordered completed action evidence to determine the
outcome. A requested stop targets only that bound current run. A cloud authority
expiry or revocation requests a stop; it never grants another play. Terminal
quiescence and release are read back before `stop_confirmed: true` is reported.
This field means observed terminal quiescence, including successful completion,
not merely that someone clicked Stop. An explicit operator cancellation before any mutation also confirms
that this command submitted no physical action; generic validation/transport
failures remain conservatively unconfirmed.

This is a **Protocol Engine workflow adapter** accessing the connector-owned
robot HTTP interface. It is not a SiLA whole-workflow command. The independent
SiLA server/bridge remains a separate runtime. On a real robot the qualified
HTTP server must use the connector's shared hardware controller; starting a
second competing server or enabling motion during installation is unsupported.

## Lost responses and recovery

One process holds an exclusive installation lock. SQLite commits each claimed
command and each mutation-attempt phase before network I/O. A command ID is
attempted once. Terminal receipts are immutable and retained in an outbox until
Academy acknowledges them. Only the identical receipt may be retransmitted.

After a crash, every unfinished command becomes `unknown`; the companion never
replays uploads, create-run, play, stop or release. A timeout after any robot
mutation also becomes unknown. An unresolved unknown blocks further local
execution, and the server retains its physical device lock. There is intentionally
no "delete journal and retry" recovery button. Inspect the physical robot and
original bound run, preserve the journal and receipts, and perform the separate
operator reconciliation procedure before requalifying an installation. The
companion fetches the administrative resolution from the authenticated,
installation-bound command GET endpoint. It validates the original command and
profile/release identities, known Protocol Engine IDs, server revision, evidence
digest and confirmed stopped/released state. The resolution explicitly preserves
historical `unknown` and forbids replay. It is appended to a separate immutable
SQLite audit table. Only a new command ID may proceed after this resolution;
the original command and unknown receipt are never rewritten or replayed. A local
JSON assertion, mismatched response or revoked credential cannot unlock it. Do not
rename/delete state to bypass the lock. If the network is unavailable during
motion, use the instrument's local stop/emergency control as appropriate; a cloud
button is not an emergency stop.

## Package staging

The safe staging helper supports reviewed GitHub Actions ZIP artifacts and tar
archives. It snapshots and hashes the downloaded archive, rejects
checksum mismatch, symlinks/hardlinks/devices, absolute/traversing paths, duplicate
members, privileged modes, excessive files and excessive compressed/expanded
bytes. ZIP entries additionally reject encryption, unsupported compression
methods and expansion above the configured 200:1 ratio. It extracts into a private new directory and refuses to replace an active
installation. It does not execute any installer or download an unapproved build.

```sh
python -m academy.companion stage \
  --archive /absolute/download/approved-package.zip \
  --sha256 VERIFIED_APPROVED_MANIFEST_SHA256 \
  --destination /absolute/private/staging/new-release
```

The digest argument is the artifact checksum from the reviewed approved manifest,
not the checksum of the manifest itself. Artifact promotion/signing, trusted
manifest distribution, robot OS-specific deployment and rollback belong to the
release pipeline. Staging alone is not installation or physical qualification.

## Software verification

```sh
uv run pytest app/backend/tests/test_connector_protocol.py app/backend/tests/test_connector_companion.py
```

Fixtures use actual loopback HTTP sockets and the production httpx Protocol
Engine transport. They cover read-only probing, compiler constraints, operator
decline, identity mismatch, active-run refusal, analysis failure, missing command
evidence, bound stop, no redirects, lost play/receipt responses, process locking,
restart/no-replay, authenticated administrative resolution/new-command recovery,
periodic verified idle probes, large historical run lists, and safe ZIP/tar staging. Cloud transport fault fixtures do not claim
live AWS identity. A further full installed-package → approved connector → actual
robot commissioning run, with physical inspection and stop/recovery checks, is
required before production enablement.

Protocol Engine schema reference used for adapter implementation:
[Opentrons v8.5.1 robot-server](https://github.com/Opentrons/opentrons/tree/v8.5.1/robot-server/robot_server).
Exact compatibility remains bound to the locally qualified firmware/API profile;
this source reference is not a compatibility certification for untested robots.


## Optional vendor simulator smoke

`python -m academy.companion.simulator_smoke` runs only in a separate reviewed
environment already containing `opentrons==9.0.0`. It uses the explicit vendor
software simulator with isolated temporary configuration and real schema-2
Opentrons tip rack, NEST reservoir and Corning plate definitions. It does not load
a hardware controller or contact a robot. On 2026-10-24 both Flex and OT-2
compiled plans completed pickup → aspirate 100 µL → dispense 100 µL → drop. The
actual engine emitted pickUpTip, aspirate, dispense and dropTipInPlace. This
check found and fixed the API 2.20 OT-2 fixed-trash compatibility issue. Engine
homing is part of a simulated played run, not a companion startup command.
These results establish software API compatibility, not Matterix, SiLA wire,
installed connector or physical acceptance.

## Reviewed robot installer

The separate `academy-bridge setup` entry orchestrates the pinned upstream Flex
installer, service switch and rollback under a reviewed recipe. See
[INSTALLER.md](INSTALLER.md) for its local trust inputs, credential bootstrap,
unknown-outcome journal and first-install recovery. It snapshots committed source
objects instead of copying a dirty checkout, verifies the catalog-bound recipe and
package, and requires local confirmation before changing robot services. Upstream
runtime code remains in its independent repository.

An offline `academy-bridge doctor` checks the bundled Python/SiLA dependency
without contacting a robot. Neither this check nor safe archive staging establishes
an installed connector. No installation recipe or robot artifact is currently
approved, and no physical installation has been attempted. OT-2 automatic
activation remains unavailable until its transactional installer and process
identity endpoint are qualified.
