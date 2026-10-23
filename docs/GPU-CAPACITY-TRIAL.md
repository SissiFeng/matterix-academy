# Bounded Canadian GPU capacity trial

Decision checked on 2026-10-23: the authorized development account has an applied
8-vCPU G/VT On-Demand quota in `ca-central-1`; the requested 16-vCPU increase is
still pending. `g6.2xlarge` is offered in `ca-central-1a`, `1b`, and `1d`. An offering
does not guarantee launch capacity. `g6e.2xlarge` is absent from this region's EC2
type API and price catalog; US East's G/VT quota is still zero.

For this bounded trial, select `build_instance_type: "g6.2xlarge"` in the protected
Packer JSON. The normal default remains `g6.4xlarge`. This revises the earlier
preference to measure the 64-GiB host first: a full L4, 8 vCPU and 32 GiB can now be
tested within the applied quota. The 32-GiB model meets NVIDIA's minimum RAM spec;
its startup and complete-workflow capacity remain unmeasured until executed.
No additional approval flag is needed for this already-authorized trial.

The guarded build reads the selected EC2 type using the exact frozen credentials
verified by STS. It requires x86_64, at least 8 vCPU and 32 GiB physical RAM, and
one full L4/L40S with at least 22,000 MiB VRAM. It checks the **applied** quota and
refuses to overlap another pending/running/stopping G/VT instance. Keep build and
acceptance sequential; these checks are not an atomic account-wide reservation.

Run the existing `scripts/ec2-gpu-build.py build` wrapper with the protected
configuration and the existing paid-build/license flags. Its default local
timeout is 7,200 seconds (two hours), adjustable with `--timeout-seconds` from 60
to 9,000 seconds. Timeout first interrupts Packer so its normal cleanup can run,
then allows five minutes before termination and one minute before forced kill.
The local timeout is **not a billing cap**: inspect the Packer log and reconcile
the build's instances, volumes, AMIs, snapshots, keys and security groups after
any failed/interrupted build. Never remove another workload's resources.

The unchanged native probe must load the pinned internal Flex scene, render at
least three nonblack 960×540 frames, reset and close successfully. It is bounded
to 30 minutes plus a 30-second termination grace. Finalization retains:

- `scene-render.json`: native frame count and measured scene startup, render and reset times.
- `capacity.json`: elapsed time, GNU time peak process RSS, sampled peak GPU memory,
  CPU count, OS-visible RAM and kernel OOM evidence. Linux reserves part of physical
  RAM, so this host check allows 31 GiB visible after EC2 verifies 32 GiB physical.
- `probe-time.txt`, `gpu-memory.csv`, `probe-kernel.log` and measurement timestamps.

These files live in `/etc/academy-native/evidence/`. Compact capacity and scene
reports also print to Packer's local log before failed-build cleanup can remove
the host. A killed/timed-out process, missing measurements, unreadable kernel log,
or any observed kernel OOM fails finalization. Do not publish an image after such
a failure. Do not add swap or lower source/version/render/reset gates to obtain a
pass. Keep raw timing/GPU logs from a successful image for review.

Passing this probe establishes measured image startup/render capacity only.
It neither runs the five-step workflow nor qualifies the worker. Real decoded
browser video, refresh recovery, reset/release and a second complete run remain
separate commissioning gates. With learner login acceptance deferred, create no
idle acceptance instance merely to wait for a user.

The official price feed was published 2026-10-22 and read 2026-10-23. Canadian
Linux On-Demand `g6.2xlarge` is USD 1.08547/hour versus USD 1.46920/hour for
`g6.4xlarge`. A two-hour compute trial is about USD 2.17, plus IPv4 and storage.
The retained 300-GiB gp3 volume is USD 26.40/month; AMI snapshots, KVS, traffic and
logs are extra. The initial operational target remains at most eight total GPU
compute hours. No one-hour build completion or total bill is promised.

Sources:

- [NVIDIA Isaac Sim 6.0 requirements](https://docs.isaacsim.omniverse.nvidia.com/6.0.0/installation/requirements.html)
- [AWS G6 hardware specifications](https://aws.amazon.com/ec2/instance-types/g6/)
- [AWS regional instance support](https://docs.aws.amazon.com/ec2/latest/instancetypes/ec2-instance-regions.html)
- [AWS Canadian Linux On-Demand price feed](https://b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps/ec2/USD/current/ec2-ondemand-without-sec-sel/Canada%20%28Central%29/Linux/index.json)
