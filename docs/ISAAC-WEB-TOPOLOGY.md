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

## First integration target: existing OT Flex workflow

The operator clarified that the pouring demo is still being debugged. It is excluded from the first onboarding integration. Use an existing OT Flex workflow instead; the exact previously working workflow is being confirmed with the operator.

Live GitHub metadata and local source inspection identify [Matterix PR #59](https://github.com/ac-rad/Matterix-Internal/pull/59) as the Flex implementation. [PR #58](https://github.com/ac-rad/Matterix-Internal/pull/58) concerns the OT-2 97-body tip-rack collection. The corresponding Flex USD assets are in [assets PR #11](https://github.com/ac-rad/Matterix_assets_internal/pull/11).

| Field | Verified source candidate |
|---|---|
| Code branch / commit | `codex/flex-liquid-handler` / `18a96b78ee989fbf4e480e9db6a588c148c6adbe` |
| Assets branch / commit | `codex/flex-gripper-asset` / `c57f12a04079a5f99405e1fcb818a3b7ccc52e5b` |
| Mixing task | `Matterix-Flex-Mixing-v1` |
| Mixing workflow | `mix_four_vials` |
| Other registered mixing-task workflows | `left_tip_cycle`, `right_tip_cycle` |
| Pipetting task alternatives | `Matterix-Flex-Pipetting-v1`: `tip_pickup_and_release`, `tip_rack_cycle`, `tip_liquid_cycle` |

The current mixing source removes the shared C1 lid with the gripper and parks it on D4, selects four distinct source vials from eight using a fixed seed, and transfers 10 µL from each to D1 A1. Each transfer uses a fresh left-tool tip (`Tips__A1` through `Tips__A4`) followed by disposal. Expected final mixture: 40 µL, four tips used. The PR prose still describes one tip; the current code implements four. These are semantic liquid/attachment models, not fluid-dynamics or grasp-force acceptance.

### Existing launch and result tooling

The preserved local validation checkout at `/Users/sissifeng/Matterix-Internal-flex-tip-validation`, commit `51e0371d6e3e560d852387d6187b2a6a29129e61`, contains `scripts/run_flex_mixing_ubuntu.sh`, `scripts/smoke_flex.py`, and `_flex_mixing_validation.py`. These helpers are not tracked in the PR #59 source checkout and must not be assumed present after a fresh PR checkout. The old remote validation branch was removed; do not use its branch name as a deployment dependency.

The historical wrapper uses the `matterix-flex-lab3` Conda environment and calls `smoke_flex.py` with `Matterix-Flex-Mixing-v1`, `mix_four_vials`, seed 42, a bounded 16,000-step workflow, Kit visualization, recording and `--keep_open`. It defaults to eight environments. First web integration should use one environment and one active run; the actual installed code/assets/environment paths must be verified before reusing the wrapper.

The wrapper currently updates assets before running. A platform launch profile must instead use a prepared, pinned code/assets release. The generic `scripts/run_workflow.py` loops over episodes while the app is open and resets state machines after environment termination; it is not an at-most-once learner runner without adaptation. Preserve single execution and explicit terminal results in the web adapter.

The validation helpers already expose workflow outcome, selected sources, tip pickup/disposal order, source/mixture amounts, lid state, and MP4/result artifacts. `FLEX_MIXING_PASS` is a checked terminal report; a `.state.json` file can contain observations from before acceptance and is not a pass. Continuous run-bound progress still needs an adapter emitting native action transitions and observations with run/session/generation IDs and ordered timestamps. The existing teaching lesson and `mix_four_vials` have different plans and parameters; they must not be silently substituted for one another.

No fresh Ubuntu run or streaming acceptance was performed in this source review. Use the operator's known-working Flex setup as the runtime baseline after identifying its exact workflow and revisions. Browser connection must be ready before the instructional actions begin, with a bounded wait for the viewer. Replace indefinite `--keep_open` behavior with an explicit, bounded end-of-run viewing lease, followed by verified cleanup. Refresh reattaches to the same run and never starts the command again.

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
2. **Prove one private live viewport.** Use the operator's existing network access to test the selected OT Flex workflow, first rendered frames and reconnect. Keep the pouring demo out of this integration. This validates runtime/client compatibility only; it is not student web delivery acceptance.
3. **Complete native execution binding.** Install and qualify the documented outbound worker and local gateway. Execute the saved immutable plan in the allocated runtime; report native observations, confirmed actions, and verified reset/release. Do not enable learner execution until the native contract passes.
4. **Prove browser-only media delivery.** Implement the authenticated signaling/media path and any required host adapter. Test from a browser outside the tailnet. The service must admit only the authorized run, expire/revoke viewers, and remain unable to expose a general desktop or editor input. Use view-only mode first if server-side camera restrictions are not yet available.
5. **Embed the viewer beside progress.** Add a viewport to the existing remote run panel. Bind every grant to the authenticated owner, Academy run/session, native session, and current runtime generation. Reject a stream for an old allocation. Display video connectivity separately from snapshot freshness; missing frame timestamps must not be replaced by invented latency values.
6. **Accept the complete path.** First execute the selected existing Flex workflow with its actual unchanged parameters and verify its native outcome, viewport and progress together. For `mix_four_vials`, verify four distinct sources, four fresh tips, 10 µL per source and a 40 µL final mixture. Separately qualify the parameterized 100 µL/50 µL teaching lesson when its native adapter exists. Reconnect without rerunning actions. Reject another user's media grant, revoke an expired viewer, test runtime replacement and stale updates, and verify reset before the next learner.

## Run-page behavior

The viewport is the main visual area; confirmed steps and observed quantities remain visible beside it. Queued/starting sessions show explicit preparation states. If the video drops but status is fresh, show **Video disconnected** while retaining native progress. If status is stale but video continues, show **Status delayed** and do not infer completion from motion. Refresh retrieves the same run and requests a new authorized viewing session; it never submits a new experiment.

Both paths must identify the same run. Frame-to-simulation tick correlation requires support in the native media adapter and must be verified; a nearby status label alone is not frame-accurate synchronization. Closing the viewer does not cancel the experiment. After native completion, show the recorded run result; replay requires an explicitly implemented recording feature and is not provided by a live WebRTC stream alone.
