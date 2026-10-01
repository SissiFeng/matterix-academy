# Lab Onboarding

Lab Onboarding is a laboratory automation onboarding and training platform. Its scope spans simulation practice and supervised work on real devices. Matterix provides the digital-twin engine for the simulation path. Device connectors expose real instruments through SiLA Features backed by their native SDKs, APIs or protocols.

## Training paths

| Path | Purpose | Current boundary |
| --- | --- | --- |
| Simulation: teaching model | Learn equipment, plan workflows, make predictions and practice with immediate feedback. | Available locally. Liquid bookkeeping and deck illustrations are synthetic teaching models. |
| Simulation: Matterix digital twin | Execute a workflow in a qualified Ubuntu simulation runtime and inspect its confirmed state. | Integration and qualification work is ongoing. Control-plane code or passing fixture tests do not establish a working native connection. |
| Real devices | Prepare an instrument, complete supervised practice and demonstrate operational competence. | Planned. This application currently has no enabled physical-device execution path. |

The same experimental intent can be taught in simulation and later exercised on a real device. Each execution must identify its environment, target and evidence source. A simulation result must never become a physical-device result or grant hardware authorization. Device readiness, supported operations, calibration and access must be checked against the actual target.

## Curriculum

The curriculum connects sample preparation, measurement and optimization. It includes workflow discovery, experimental design, equipment operation and an optional developer path for understanding and building connectors. Training is broader than using a particular liquid handler or simulator.

Learners progress from understanding a task, to simulation practice, to supervised physical practice where available. Hardware access, instructor review and any qualification records require explicit implementation and lab acceptance. Simulation completion alone is not certification.

## Responsibilities

- Lab Onboarding owns learner identity, curriculum, training records and the learner experience.
- The simulation runtime owns simulated execution and observations. Matterix is one runtime integration.
- A future real-device execution service must own physical run authorization, instrument exclusivity, recovery and records of actual observations. The connector translates device capabilities; a Feature wrapper alone is not a complete training or safety policy.
- The lab operator or instructor owns physical setup, supervision and the decision that a learner may operate an instrument.

Simulation-only qualification, including a `no_hardware` guarantee, must not be repurposed as authorization for real instruments. Extending this platform to real execution requires a distinct capability and authorization contract.

## Naming and compatibility

Use **Lab Onboarding** in product copy, interface titles and current project descriptions. Use **Matterix** when referring to its simulation engine or specific integration.

Existing repository paths, Python imports, environment variables, database names, IAM resources, OAuth scopes and storage keys retain their current technical identifiers during this branding change. Renaming those identifiers is a separate migration, because changing them implicitly could disconnect existing accounts, saved work or deployments. Historical validation records and pinned third-party source excerpts retain their original wording.
