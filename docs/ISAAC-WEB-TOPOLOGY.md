# Live Isaac viewport: topology review and integration sequence

Reviewed 2026-10-01. This is an integration plan, not a native execution or streaming acceptance record. Product name: **Lab Onboarding**.

## Requirement

Show the actual Matterix / Isaac simulation **while a saved experiment runs**, inside the existing web run page, beside progress and native observations for that same run. Keep the existing React frontend. Use an embedded WebRTC viewer for the Isaac-rendered viewport; a new Three.js scene is not needed to satisfy this request.

This request prioritizes the real viewport ahead of the longer-term browser-rendered twin proposed in [ACCESS-MODEL.md, section 6](ACCESS-MODEL.md). The student experience is a scoped simulation view, with camera interaction only when the server can enforce it. General desktop and Isaac editor access stay with the operator.

## What was checked

The initial cloud deployment is recorded in [DEPLOYMENT-2026-10-01.md](DEPLOYMENT-2026-10-01.md); application release behavior is defined in [CONTINUOUS-DEPLOYMENT.md](CONTINUOUS-DEPLOYMENT.md). The topology observations below are a dated, read-only snapshot.

| Boundary | Evidence on 2026-10-01 | Limit |
|---|---|---|
| Local Tailscale | Client running; MagicDNS enabled; suffix `tail6a1dd7.ts.net` | Does not prove application ports or SSH permissions |
| Workstation network | `sdl0-robot-borealis.tail6a1dd7.ts.net` resolves to `100.119.227.39`; one Tailscale ping succeeded in 6 ms over a direct path | A single network sample is not streaming latency or throughput acceptance; the running Isaac process was not inspected |
| AWS learner API | Read-only `get-function-configuration` returned `matterix-academy-dev`, `State=Active`, `ACADEMY_REMOTE_ENABLED=false` | No native execution was enabled or attempted |
| AWS control plane | [Deployment record](DEPLOYMENT-2026-10-01.md) reports the deployed API, queue, machine authorization and lease reaper | Deployment evidence explicitly excludes native Ubuntu/GPU/media acceptance |
| Native runtime and media | [Worker handoff](WORKER-CONTROL.md) and [synchronized-run contract](SYNCHRONIZED-RUNS.md) still require native qualification and authenticated media | No verified installed gateway, live stream, or viewer grant endpoint |

No SSH login, runtime restart, Tailscale policy change, port exposure, worker enrollment or new AWS resource was performed in this review.

## Concrete starting point supplied by the operator

The operator reports that the following configuration launches the desired Isaac Lab window successfully on Ubuntu. Source inspection used the exact supplied Matterix commit, not the subsequently advanced local branch. Opening the window is not itself a passing pouring verdict or a streaming acceptance test.

| Field | Supplied configuration |
|---|---|
| Checkout | `/home/sissi/matterix-semantics-pr61-b0p9uC` |
| Matterix commit | `b6a5f00036044686776ba5bc6bf0c72daa6ac17a` |
| Python | `/home/sissi/.conda/envs/matterix-pr50-py312/bin/python` |
| Entry point | `scripts/validation/run_semantics_pouring.sh` |
| Scenario | `Matterix-Test-Semantics-Pouring-Franka-v1` |
| Parameters | `--num_envs 2 --test_stage pour --video --motion_speed_scale 3 --viz kit --livestream 0 --enable_cameras --device cuda:0` |

This provides a concrete first streaming scenario before accepting arbitrary learner-composed Flex workflows. The currently implemented worker contract is scoped to the Flex lesson; the pouring probe requires its own registered scenario and observation/result mapping before the learner API can launch it.

The supplied configuration uses the local Kit visualization and disables livestreaming. `--video` records two MP4 outputs (overview and tiled close-ups); it does not deliver a live browser stream. The wrapper clears inherited `LIVESTREAM` and `HEADLESS`, so a streaming variant must use explicit, installed-version-compatible launch arguments. Do not assume setting an outer environment variable enables streaming, or that changing `0` to another value completes network integration.

At the pinned revision, the probe already provides:

- `MATTERIX_PHASE` JSON log events for startup and execution stages.
- `MATTERIX_POUR_DIAGNOSTICS` JSON log events with simulation step and per-environment action/geometry diagnostics, emitted periodically and on action changes.
- `result.diagnostics.json` with richer sampled native state and semantic events.
- `result.json`, `run.log`, and overview/close-up recordings in a unique result directory. The wrapper reports success only when `passed` is true and the simulator process exit status is zero.

The integration adapter can consume these existing events, add run/session/generation identity and ordered observation metadata, and publish them through the worker API. They do not already satisfy the platform contract: startup phases are not workflow-step completion receipts, particle counts are not calibrated liquid volumes, and these files/events do not contain Academy run identities. Reading JSON files requires handling writes in progress; a structured event sink or atomic snapshot write is preferable to assuming every file read is complete.

The probe is finite, with a default ten-minute wrapper timeout, and closes the simulation after saving results. Browser connection must be ready before the instructional actions begin, with a bounded wait so an absent viewer cannot reserve the GPU indefinitely. A terminal run should show its saved outcome and, after artifact publication is implemented, the existing recordings. It should not promise a live scene after the process has exited.

Register a versioned launch profile for this scenario. Repository preparation (`git fetch` and checkout selection) belongs to deployment; a learner run launches the prepared revision with validated parameters. Reconnection only reattaches to the recorded process/run. It must not run the shell command again.

## Topology to preserve

Solid connections below describe the existing access design; dashed connections are native/media integration still to qualify. The worker software exists, but its installation on the Ubuntu host is not verified.

```mermaid
flowchart LR
  Browser[Student browser: one Lab Onboarding page]
  Web[CloudFront / web app]
  API[AWS learner API / Cognito]
  Store[(Durable runs / snapshots)]
  Machine[AWS worker API]
  Worker[Ubuntu outbound worker]
  Runtime[Matterix / Isaac runtime]
  Media[Authenticated signaling and media service: pending]
  Operator[Operator Mac]

  Browser --> Web
  Browser <-->|HTTPS: submit and read progress| API
  API --> Store
  Worker -.->|Outbound HTTPS: claim / heartbeat / reports| Machine
  Machine --> Store
  Worker -.->|Local gateway: execute immutable plan| Runtime
  Runtime -.->|Outbound media path: version-specific adapter| Media
  Media -.->|WebRTC: live viewport| Browser
  Operator -->|Tailscale / MagicDNS: administration| Worker
```

The command/status path and the media path share a run binding, not a transport. CloudFront and the current HTTP API do not themselves relay Isaac's WebRTC media. The AWS control plane does not need to join the tailnet or dial the Ubuntu host.

### Tailscale and MagicDNS

- **Tailscale** provides the operator's private route to the workstation.
- **MagicDNS** names devices on that network. A DNS name is not an authenticated public streaming endpoint. An ordinary student browser outside the tailnet cannot gain that route merely by loading the AWS website. See [MagicDNS](https://tailscale.com/docs/features/magicdns).
- **Serve** publishes services within the tailnet; it does not fulfill the no-student-VPN requirement. See [Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve).
- **Funnel** publishes a service to the internet using a TCP proxy. It does not automatically carry the separate Isaac media transport or enforce Lab Onboarding run permissions. The existing plan does not select Funnel. See [Tailscale Funnel](https://tailscale.com/docs/features/tailscale-funnel).
- The ACL in ACCESS-MODEL.md is an example, not verified live policy. Peer visibility and a successful Tailscale ping do not establish SSH, RDP, or streaming-port access.

### Remaining media transport decision

Preserve the existing rule: no public inbound application ports on the lab host and no student tailnet membership. The media implementation must therefore prove an outbound route for **both signaling and media**, using an authenticated media service plus a host-side adapter as required by the installed Isaac version. TURN may relay media, but cannot by itself create the signaling route, bind streams to runs, or enforce viewer permissions.

Do not assume a reverse HTTPS proxy, a TURN installation, or an iframe is a complete solution. First test the installed runtime's transport capabilities. If its built-in streaming server cannot satisfy outbound-only delivery, select and validate an explicit host-side media bridge; do not silently change the network boundary.

The [official NVIDIA browser client](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/manual_livestream_clients.html) and [Omniverse Web SDK](https://docs.omniverse.nvidia.com/ov-web-sdk/latest/index.html) are the integration starting points. Pin the client to the actual runtime/extension compatibility. The screenshot's **Isaac Lab 3.0.0** label does not identify the Isaac Sim/Kit version. Current NVIDIA documentation permits one direct streaming client per Isaac instance, so start with one active learner and a queue. Multiple simulated environments in one viewport are not isolated student streaming sessions.

## Implementation sequence

1. **Inspect the installed host without disturbing its current run.** Confirm the intended workstation, SSH account, Matterix/assets commits, Isaac Lab/Sim/Kit and streaming-extension versions, GPU encoding support, launch command, current process and available ports. Record the facts before choosing a streaming client or launcher flag. A finite smoke-test script is not a persistent session service.
2. **Prove one private live viewport.** Use the operator's existing network access to test the actual Matterix scene, first rendered frames and reconnect. This validates runtime/client compatibility only; it is not student web delivery acceptance.
3. **Complete native execution binding.** Install and qualify the documented outbound worker and local gateway. Execute the saved immutable plan in the allocated runtime; report native observations, confirmed actions, and verified reset/release. Do not enable learner execution until the native contract passes.
4. **Prove browser-only media delivery.** Implement the authenticated signaling/media path and any required host adapter. Test from a browser outside the tailnet. The service must admit only the authorized run, expire/revoke viewers, and remain unable to expose a general desktop or editor input. Use view-only mode first if server-side camera restrictions are not yet available.
5. **Embed the viewer beside progress.** Add a viewport to the existing remote run panel. Bind every grant to the authenticated owner, Academy run/session, native session, and current runtime generation. Reject a stream for an old allocation. Display video connectivity separately from snapshot freshness; missing frame timestamps must not be replaced by invented latency values.
6. **Accept the complete path.** Run the 100 µL lesson and 50 µL variation. Confirm the submitted volume/layout reaches that runtime, its live viewport appears during execution, and native reports drive progress. Reconnect without rerunning actions. Reject another user's media grant, revoke an expired viewer, test runtime replacement and stale updates, and verify reset before the next learner.

## Run-page behavior

The viewport is the main visual area; confirmed steps and observed quantities remain visible beside it. Queued/starting sessions show explicit preparation states. If the video drops but status is fresh, show **Video disconnected** while retaining native progress. If status is stale but video continues, show **Status delayed** and do not infer completion from motion. Refresh retrieves the same run and requests a new authorized viewing session; it never submits a new experiment.

Both paths must identify the same run. Frame-to-simulation tick correlation requires support in the native media adapter and must be verified; a nearby status label alone is not frame-accurate synchronization. Closing the viewer does not cancel the experiment. After native completion, show the recorded run result; replay requires an explicitly implemented recording feature and is not provided by a live WebRTC stream alone.
