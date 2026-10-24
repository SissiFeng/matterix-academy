# Lab Onboarding

A laboratory automation onboarding and training platform spanning simulation practice and supervised work on real devices. Learners explore experimental design, discover workflows, practice Flex operations and understand connector development. Matterix supplies the digital-twin engine for the simulation path; it is not the platform identity.

The interface remains English. The implementation uses React + TypeScript and FastAPI, with independently deployable AWS infrastructure. See [product scope and training paths](docs/PRODUCT-SCOPE.md) for the distinction between simulation, physical-device training and currently available execution.

**Current release:** interactive Flex and OT-2 introductions, a visual Workflow Studio for student designs, a guided English-language first-transfer lesson, the original three-stage serial dilution workspace, workflow discovery, connector learning and a workcell onboarding workspace. Lesson execution in the browser uses an explicitly synthetic teaching model: no physical robot, GPU physics, collision checks or chemical predictions are connected. A durable outbound-worker control plane, a pinned native Flex mixing adapter and KVS WebRTC viewer are implemented, but native execution stays disabled until a real Ubuntu host passes qualification. **See [docs/STATUS.md](docs/STATUS.md) for what is verified, what is only implemented, and what is blocked.**

**AC development deployment:** [Open Academy](https://d2m3yolcjdy6d2.cloudfront.net). Infrastructure and application publication are verified; a learner invitation is needed for sign-in. The durable outbound-worker control plane is implemented, while native execution stays disabled pending Ubuntu qualification. See [deployment evidence and remaining acceptance](docs/DEPLOYMENT-2026-10-01.md) and [worker operations](docs/WORKER-CONTROL.md).

## Run locally

The public welcome page and signed-in Overview now begin with **Meet the instruments**: choose Flex or OT-2, watch a common workflow, then open it in the visual **Workflow studio** or begin with a blank deck. See [introductions and studio](docs/INSTRUMENT-STUDIO.md) for the full journey and teaching limits.

The workcell tools remain available under **Overview → Onboard → Twin → Sim → Real → Runs**. Register a Flex, save its connection plan and capability declarations, pair a teaching session, and inspect saved trial evidence next to explicitly missing physical observations. The five-step device wizard persists progress and protects concurrent edits. See [workcell onboarding](docs/WORKCELL-ONBOARDING.md) for the user flow and evidence boundaries. Existing lessons and native simulation remain available under **Learn & Explore**.

Requirements: Node.js 22.12+, Python 3.12 and [uv](https://docs.astral.sh/uv/).

The local Sim → Real workspace also includes **Connect an instrument**: register
a Mac, pair a local companion, inspect the connected robot and review a saved
workflow against native DT evidence. See [connector setup](docs/connectors/SETUP.md)
for the candidate Mac bundle, private S3 publication, operator qualification and
recovery. This feature has not been deployed or accepted on physical hardware;
the shipped catalog has no approved robot releases and physical execution stays
disabled by default.

```sh
bash scripts/dev.sh
```

Open [the learning lab](http://127.0.0.1:5173). The API listens on loopback port 8000. Local sign-in creates a signed, HttpOnly, 24-hour guest cookie. Its data persists in `.data/academy.sqlite`; this is a local preview identity, not a replacement for a production account. Signing out ends access to that guest identity. No passwords, AWS credentials or Matterix installation are needed for the preview.

Choose **Start learning Flex** for the guided first lesson. Its checks and predictions persist with your experiment; editing the deck or restarting invalidates the relevant preparation. The first lesson is complete only when the transfer passes and the learner correctly explains aspiration. Reset preserves up to ten attempt summaries, including the previous prediction and explanation.

The original **Start an experiment** opens the dilution sandbox. Its default method reaches 50%, 25% and 12.5% stock concentration under instantaneous ideal mixing. Delete the first tip pickup or set a transfer above the teaching model's 300 µL limit to explore failure feedback. This is not a physical mixing model or a specification for every Flex pipette.

The Learning lab also includes **Can this workflow run?**, an English workflow
judgment course: identify gaps, repair a synthetic dilution plan, inspect teaching
results and reconcile a scripted timeout before concluding. Progress is saved per
learner. See [course behavior and evidence boundary](docs/WORKFLOW-JUDGMENT-COURSE.md).

The **0.2.0 internal Flex source release** includes bounded browser commissioning
and a hash-locked GPU image recipe. See [image build and release inputs](docs/GPU-IMAGE-BUILD.md)
and [browser commissioning](docs/COMMISSIONING.md). This does not enable the live
GPU service or label teaching results as native evidence.

[Matterix main synchronization](docs/MATTERIX-MAIN-SYNC.md) detects changes in the
independent internal engine and assets repositories and prepares an unqualified
candidate report and draft PR. New features require an adapter, versioned recipe,
English learning content and qualification before they become runnable. The
scheduled intake requires a dedicated GitHub App; it never starts paid GPU builds
or changes a running worker.

## What is included

- Three-step account introduction followed by a five-stage, checkpoint-based novice lesson, equipment glossary, preparation checklist, predictions, step explanations and reflection.
- Labeled equipment illustration and an honest remote-connection status view; the illustration is not live 3D.
- Click/keyboard placement of movable items on a schematic Flex deck. The waste chute is fixed at D3; occupied movable slots swap. This does not validate geometric reachability.
- Editable action sequence, volumes, source/destination, ordering and starting liquid amounts.
- Run, pause, single-step, reset, observations, goal assessment and saved experiments.
- Server-owned state, per-user storage keys and optimistic concurrency checks. Invalid actions produce visible errors without partial transfers.
- AWS Cognito authorization-code/PKCE login; API Gateway validates JWTs and scopes, and Lambda rechecks trusted authorizer claims.
- Private S3 + CloudFront website, API Gateway + FastAPI/Mangum Lambda, DynamoDB, logs, basic error alarm and a scoped optional GitHub OIDC deployment role.
- CI checks and automatic AWS application deployment after a tested commit reaches `main`. Releases carry a verified commit/checksum manifest; Terraform manages infrastructure separately.

No Three.js is included. The schematic deck is ordinary React/CSS; future Matterix 3D views will use a separately qualified streaming integration.

## Verify

```sh
uv sync --frozen
npm --prefix app/frontend ci --include=optional
bash scripts/build-lambda.sh
bash scripts/verify.sh
cd app/frontend
npx playwright install chromium
npm run test:e2e
```

Tests cover teaching behavior, conservation, error recovery, ownership, stale and concurrent requests, SQLite and mocked DynamoDB, AWS authorizer context and browser journeys. Mocked AWS tests do not establish deployed AWS behavior. Lambda packaging downloads Linux x86_64 wheels even when built on macOS.

## Repository map

| Path | Responsibility |
|---|---|
| `app/frontend` | Student interface and Cognito browser sign-in |
| `app/backend/academy` | Profile, courses, session lifecycle and teaching runner |
| `app/backend/academy/gateway.py` | Typed client for the proposed Ubuntu gateway contract; no automatic command retries |
| `infra` | Standalone Terraform AWS stack |
| `docs/AWS.md` | Bootstrap, deployment, operations and rollback |
| `docs/MATTERIX-CONTRACT.md` | Integration boundary and required qualification |
| `docs/SYNCHRONIZED-RUNS.md` | Whole-workflow execution, authoritative progress, reconnection and video synchronization |
| `docs/ARCHITECTURE.md` | State ownership, limitations and design choices |
| `docs/LEARNING-EXPERIENCE.md` | Novice curriculum, target experience and implementation boundaries |
| `docs/REMOTE-UBUNTU.md` | Administrator handoff for connecting the existing Ubuntu host |
| `docs/STATUS.md` | Single current status: verified, implemented-but-unverified and blocked work |
| `docs/ENDPOINT-COMMUNICATION.md` | Communication design across browser, AWS, host agent, Isaac runner, media and operator |
| `app/backend/academy/native_plan.py` | Learner plan → native intent translation and scene-capability preflight |

The existing Matterix code and asset repositories remain independent. Do not duplicate its physics or robot execution logic here.
