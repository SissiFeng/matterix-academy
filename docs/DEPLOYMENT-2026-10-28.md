# AWS runtime recovery — 2026-10-28

## Observed deployment

STS verified the existing SDL0-DEV1 account `247893369214` using
`pas-sdl0-dev`, in `ca-central-1`. No infrastructure was created or account changed.
The live [Academy](https://d2m3yolcjdy6d2.cloudfront.net/) release is
`118b6ed3a398506481c2f778568b81a3b2561a69`, published by successful
[deployment 40382171466](https://github.com/SissiFeng/matterix-academy/actions/runs/40382171466).
Health returns OK; `/api/config` reports native Matterix unavailable. All four
application/worker Lambdas retain `ACADEMY_REMOTE_ENABLED=false`.

`i-0de8aa02fe37aa58d` is the existing `academy-gpu-pilot`, a Canadian
`g4dn.2xlarge` / Tesla T4 with 15,360 MiB driver-visible memory, 32 GiB advertised
RAM and a retained 300-GiB encrypted gp3 root. Its prepared AMI is
`ami-01b1fd7bb2acde950`. SSM is reachable. The worker was inactive before this
investigation; the cloud worker remains quarantined and unqualified.

## Capacity is distinct from regional support

Live EC2 offerings list G6 xlarge/2xlarge/4xlarge in this account's Canadian
AZs `1a`, `1b`, `1d`; G5 in `1a`, `1b`. CloudTrail records actual
`InsufficientInstanceCapacity` failures for G6.2xlarge in all three and
G5.2xlarge in both, including attempts on October 28. AWS error suggestions
pointing to another AZ were not capacity guarantees.

The applied G/VT On-Demand limit remains 8 vCPU; the existing request for 16
remains `CASE_OPENED`. The G4 uses all 8. G5.2xlarge and G6.2xlarge each need 8;
G6.4xlarge needs 16. Do not run another GPU alongside the pilot or treat the
pending quota request as approved. No new allocation or reservation was attempted.

## Confirmed runtime blocker and fix

The pilot permits TCP/UDP 443 egress. Its Isaac Lab configuration already names
HTTPS NVIDIA S3, but the Omni client logs select
`http://dcb18d6mfegct.cloudfront.net/`. Ground construction blocks in
`isaaclab.utils.assets.retrieve_file_path` → `omni.client.copy`; the downloaded
asset tree would otherwise be placed in temporary storage. A direct HTTPS request
to the original NVIDIA S3 ground succeeds; the corresponding HTTP request times out.
The build host and restricted runtime therefore have different download behavior.

`academy.native_assets` pins the original NVIDIA 6.0 ground USD and its three
referenced textures by SHA256. The explicit preparation command (also verified live from an empty cache on October 28) downloads only
those files over HTTPS, rejects redirects/oversized/mismatched responses, and
atomically installs validated files into the private persistent cache. Native
startup verifies all four hashes before launching Kit and fails promptly if any
are missing or changed; it performs no network download. The pinned Matterix
module's ground-config factory is bound in memory to the local USD. Its placement,
color, physics material and dimensions are preserved. Independent source trees,
installed Isaac files, GPU settings, 960×540 resolution and reset gates are unchanged.
The existing PR #17 headless/camera/child-exit fixes are prerequisites.

New images prepare these dependencies in `finalize.sh` before native probes.
For this existing pilot, the two Academy adapter files were installed with a
checksum guard against the observed prior PR #17 version, preserving a backup.
This is an operator-patched pilot, not a newly published/qualified AMI.

## Real GPU evidence

The old image's scene report records 417.237 seconds startup, 29 nonblack frames,
5.576 seconds render probing and 0.025 seconds reset. Its Studio probe passed
locally; capacity sampling saw 3,473 MiB peak GPU usage without kernel OOM.

On October 28, two sequential local-ground scene probes on the same T4 reported:

| Probe | Scene startup | Render probe | Reset | Nonblack frames |
|---|---:|---:|---:|---:|
| First | 24.507 s | 3.373 s | 0.025 s | 29 |
| Second | 23.749 s | 3.315 s | 0.024 s | 29 |

These are warm-host measurements, not a controlled cold-boot GPU comparison.
EBS hydration, filesystem/shader cache and earlier initialization can contribute
to the difference from the historical 417-second observation. The blocked online
copy and successful local-resource path are directly reproduced. No G5/G6 speed
claim follows from these measurements.

The installed adapter then passed its full standalone Studio probe in **214.82 s**
(exit 0), with 723 nonblack frames, four confirmed workflow steps, stock/A1 volumes
900/100 µL, empty pipette, no attached tip, and all four native reset checks true.
Peak process RSS was 9,892,256 KiB. Its report explicitly leaves browser qualification
false. [Sanitized native evidence](evidence/ec2-gpu/runtime-recovery-2026-10-28.json)
binds the snapshots, frame proof, reset receipt, source pins and adapter checksums.

Evidence remains under `/var/lib/academy-native/timing-20261028` on the pilot.
The initial online timing service was stopped after reproducing the blocked
copy. A first integrated Studio probe encountered a missing `/run/academy-native`
after the stopped worker's RuntimeDirectory was removed; the standalone probe
setup recreated that directory before a new independent probe. Production
systemd normally creates it. No prior learner run was replayed.

## Real browser recovery and acceptance

The learner subsequently signed in and completed real browser acceptance after
[PR #20](https://github.com/SissiFeng/matterix-academy/pull/20) repaired the regional
KVS CSP and empty signaling-frame handling. The verified live release is
`e54b4ac68e8d1883c1f1b668b44cefacf9965527`, deployment
[40754236748](https://github.com/SissiFeng/matterix-academy/actions/runs/40754236748).
The pilot retained the reviewed adapter from `1d0e7892d39ef6ce8081f44b1cfc37afbd07c9c1`.
See [video recovery](DEPLOYMENT-VIDEO-2026-10-28.md) for the two earlier failed
zero-transfer runs, their verified final cleanup, and the specific signaling bugs.

The consumed failed grant was explicitly retired with expected version 4 → 5;
its complete original authority was preserved in an operator audit record. Both
failed run records remain unchanged. A separate one-hour window authorized the
same two exact designs, with a new grant and fresh run IDs; neither old run was replayed.
The worker remained quarantined, unqualified, and idle before the new window.

| Real browser run | Tips | Transfer | Final stock / A1 | Browser decoded frames | Final reset |
|---|---|---:|---:|---:|---|
| `ecc78311-528b-4a20-8c9d-83a84b590f3d` | B1 | 100 µL | 900 / 100 µL | 3,176 | Verified |
| `4c8b827d-52db-40e8-befa-9e91919847d9` | C1 | 50 µL | ≈950 / ≈50 µL | 5,199 | Verified |

Both ran all four saved actions and 21 native actions. First-run refresh recovered
the same run without another POST and decoded 2,359 frames after refresh. Browser
receipts report exactly two submission POSTs, completed status and no issues.
Native frame proofs retain 780 / 690 nonblack frames. The existing evidence
evaluator passed all eight checks, binding exact plans, runtime inventory, native
snapshots, rendered frames, browser relay observations and final stopped/reset receipts.
[Sanitized evidence](evidence/ec2-gpu/native-browser-recovery-2026-10-28.json)
contains the exact source/image pins, proof hashes and finite native-semantic amounts.
Full manifests and browser receipts remain private because execution manifests may
contain short-lived worker authority.

A real Chrome screencast records workflow creation, both runs, first-run refresh,
changed amounts/slot, rendered motion and final reset. The H.264 file is 1350×940,
15 fps and about 9:38; a 4:38 excerpt starts with the second design change. No
rendered teaching animation substitutes for the live native viewport. The file
decoded without errors, and representative native motion/result frames were
visually inspected; this is not a frame-by-frame movie review.

## Remaining acceptance

The bounded browser video, refresh and changed-design path above passed. Broader
isolation, interruption/recovery, image publication/identity and learner-capacity
acceptance remain separate. Global native execution stays off and the worker
remains quarantined/unqualified; no physical hardware was enabled. Do not promote
the worker solely from this successful two-design demonstration.

## Software validation

Lambda packaging passed; `bash scripts/verify.sh` passed with 1,416 backend tests,
frontend build/format and offline Terraform validation including the zero-resource
pilot plan. The initial shell selected Node 18 and lacked the optional native
bundler/browser packages; checks were rerun after selecting installed Node 22.15
and installing dependencies and the Playwright Chromium test browser.
The original **81 Playwright journeys passed** (3.9 minutes). The independent
video hotfix subsequently passed 1,406 backend tests and **85 Chromium journeys**,
including four new real-component/CSP regression tests; its CI and deployment passed.
The real-account native video/refresh/two-design evidence above is separate from
these synthetic teaching and signaling fixtures.

After retaining evidence and verifying both the worker and native processes were
inactive (GPU memory/use zero), the existing pilot was stopped to avoid idle GPU
compute charges. The encrypted root and artifacts are retained; storage charges
continue. No worker registration or learner-run record was changed.
