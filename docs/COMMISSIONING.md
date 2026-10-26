# Internal Flex GPU commissioning

Status: tooling prepared; native browser acceptance has not run. See [STATUS.md](STATUS.md)
for the latest image, deployment and resource evidence. The user resumed real DT
delivery on 2026-10-26; the separate learner registration/two-account exercise remains
outstanding. Saved Workflow Studio designs use [STUDIO-NATIVE-ACCEPTANCE.md](STUDIO-NATIVE-ACCEPTANCE.md).
The acceptance target is the existing Onboarding browser → Simulation lab → Four-source
mixing → native Isaac video → five completed steps → verified reset/release, twice.
Synthetic tests do not satisfy this target.

## Reviewed source and image inventory

| Component | Required candidate |
|---|---|
| Matterix internal | `ac-rad/Matterix-Internal` at `18a96b78ee989fbf4e480e9db6a588c148c6adbe` |
| Internal assets | `ac-rad/Matterix_assets_internal` at `c57f12a04079a5f99405e1fcb818a3b7ccc52e5b` |
| OS / Python | Ubuntu 24.04 x86_64 / Python 3.12 |
| Isaac Lab | `3.0.0b2.post1`; upstream tag v3.0.0-beta2.patch1 at `ffff603eafc6b74264a5261cc0183d6a65390d78` |
| Isaac Sim | `6.0.1.0`, explicitly required by the Lab wheel's isaacsim extra |
| PyTorch / torchvision | `2.11.0+cu128` / `0.26.0+cu128` |
| NVIDIA Linux driver | `595.58.03`, candidate from version-specific requirements |
| GPU | Single A10G/L4/L40S with at least 22,000 MiB, or authorized g4dn.2xlarge T4 trial with 16,384 MiB from EC2 and at least 15,360 MiB driver-visible; native fit still requires measured probes |
| Academy release / AMI | Academy 0.2.0 local release, exact commit/hash in `ops/ec2-gpu/academy-release.json`; AMI requires an authorized build |

The Lab wheel SHA256 is
`dd32886588479ffd70f7348019aeac1582eb9ad16c40244f41d9f458f96f73c3`.
Internal Flex uses `isaaclab_physx`, `SimulationCfg.physics` and the 3.x API.
The earlier Lab 2.3 / Sim 5.1 proposal is superseded. Old README badges and Docker
4.5 defaults do not establish compatibility. Assets live directly under
`/srv/matterix-assets` (labware, robots, equipment); do not append `/data`.
Keep both private checkouts independent and clean; materialize Git LFS payloads.

Sources: [Lab release notes](https://isaac-sim.github.io/IsaacLab/develop/source/refs/release_notes.html),
[version-specific Sim requirements](https://docs.isaacsim.omniverse.nvidia.com/6.0.1/installation/requirements.html),
[NVIDIA wheel](https://pypi.nvidia.com/isaaclab/isaaclab-3.0.0b2.post1-py3-none-any.whl).
The dated source audit in `docs/evidence/ec2-gpu/` verifies the two local source
pins and materialized payloads; it deliberately fails runtime/GPU readiness on macOS.
The complete transitive dependency locks and image build recipe are now in
[GPU-IMAGE-BUILD.md](GPU-IMAGE-BUILD.md). This source audit is not an installed image
or GPU qualification.
Record installed package freeze, image ID and artifact hashes on the authorized host.

G5 capacity attempts failed in both reviewed Canadian AZs on 2026-10-26. The user
authorized the lower-memory T4 trial; [GPU-CAPACITY-TRIAL.md](GPU-CAPACITY-TRIAL.md)
records its PyTorch SM 7.5, fixed-driver and RTX compatibility sources and
USD 0.835/hour compute rate. Keep the `balanced` preset, 960×540 native frames and
all workflow, OOM, reset and browser requirements. Turing supports Ray
Reconstruction but not Frame Generation; a hardware preflight does not qualify it.

## Host fingerprint (read only)

After a separately authorized host/image deployment, run as the worker service user:

```sh
/opt/academy-agent/.venv/bin/python -m academy.runtime_inventory \
  --engine-root /srv/matterix --assets-root /srv/matterix-assets \
  --isaac-python /opt/matterix-isaac/bin/python \
  --output /var/lib/academy-native/evidence/runtime.json
```

Exit 2 blocks commissioning. This checks exact source bytes against Git objects and
LFS payload hashes without writing source caches, Python/packages, PhysX module,
launcher flags, dependency consistency and GPU/driver. The prepared image retains
`/etc/academy-native/evidence/isaaclab.whl`: its pinned publisher hash and installed
payload bytes must match before importing Lab. Missing provenance blocks acceptance.
Also verify writable state/cache, IMDS denial, SSM, free disk and the worker contract.
No inventory result qualifies a worker.

## Bounded operator window

Keep global remote execution disabled. Enroll the target worker with these exact
pins; it remains quarantined and unqualified. Fill a protected request JSON with
`grant_id` (fresh UUID), `subject` (exact API Gateway JWT subject), `worker_id`,
`engine_version`, `asset_version`, `duration_seconds` (300–3600), `max_runs` (1–2).
For the two-run acceptance use max_runs 2 and duration_seconds 3600.

The following is an explicit administrative write to an existing deployment;
run only after host and live-run authorization, not during preparation:

```sh
uv run python -m academy.commissioning authorize \
  --expected-account-id REVIEWED_ACCOUNT --table EXISTING_TABLE \
  --request /protected/commissioning-request.json \
  --runtime-report /protected/runtime.json
```

Only that subject can submit fixed seed 42 to that worker. Grant expiry bounds leases
and start/bind permission; two submissions consume the window even if a run fails.
Reauthorizing the same grant cannot extend its quota or expiration. Unreleased runs
block replacement. The grant never marks the worker qualified or enables other users.

## Actual browser acceptance

On the operator workstation, use the existing authenticated Onboarding origin:

```sh
cd app/frontend
ACADEMY_COMMISSIONING_URL=https://REVIEWED_ONBOARDING_ORIGIN \
ACADEMY_COMMISSIONING_OUTPUT=/protected/browser \
npm run commissioning:live -- --confirm-live
```

Sign in manually as the designated subject. The headed harness submits two workflows
through the real UI, checks decoded video and relay ICE statistics, reloads without
resubmitting, and requires five completed steps plus verified reset. It reads the
owner-scoped `/api/commissioning/report` through the same signed-in browser.
The harness is excluded from default tests/CI. Live native/KVS operation may incur
charges; this command has not been run as part of preparation.
Keep the browser profile, raw reports, screenshots and host journal protected;
never commit tokens, TURN credentials, signed URLs or claim journals.

Collect the runtime report and native run directories (manifest.json, snapshot.json,
frame-proof.json, released.json, release-command.json) through the approved operator
channel, then correlate locally:

```sh
uv run python -m academy.commissioning_evidence \
  --runtime-report /protected/runtime.json \
  --browser-report /protected/browser/browser-report.json \
  --runs-root /protected/native-runs --output /protected/acceptance.json
```

Exit 0 means the supplied browser/cloud/native artifacts are consistent: two distinct
fixed workflows, matching run/native IDs and plan hashes, actual browser frame reports,
nonblack native-frame proofs, complete snapshots and reset/release receipts.
The checker does not attest artifact provenance or qualify the worker. Independently
review image identity, isolation, interruption/recovery and all WORKER-CONTROL.md
requirements before separately recording qualification. General learner enablement
remains a separate deployment. A failed/unknown run must be reconciled, not replayed.
