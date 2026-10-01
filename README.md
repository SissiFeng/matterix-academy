# Matterix Academy

A browser-based learning lab for students to arrange a Flex deck, compose liquid-handling steps, make mistakes and understand the result. React + TypeScript and FastAPI, with independently deployable AWS infrastructure.

**Current release:** a guided English-language first-transfer lesson plus the original three-stage serial dilution workspace. Explore the Flex, check the deck, predict liquid movement, run a 100 µL transfer step by step, explain the result and retry at 50 µL. Both exercises are explicitly synthetic: no physical robot, GPU physics, collision checks or chemical predictions are connected. The remote Ubuntu contract client supports capability checks, session/command requests and read-only reconciliation; live sessions remain disabled until the server implementation and streaming are connected and qualified.

## Run locally

Requirements: Node.js 22.12+, Python 3.12 and [uv](https://docs.astral.sh/uv/).

```sh
bash scripts/dev.sh
```

Open [the learning lab](http://127.0.0.1:5173). The API listens on loopback port 8000. Local sign-in creates a signed, HttpOnly, 24-hour guest cookie. Its data persists in `.data/academy.sqlite`; this is a local preview identity, not a replacement for a production account. Signing out ends access to that guest identity. No passwords, AWS credentials or Matterix installation are needed for the preview.

Choose **Start learning Flex** for the guided first lesson. Its checks and predictions persist with your experiment; editing the deck or restarting invalidates the relevant preparation. The first lesson is complete only when the transfer passes and the learner correctly explains aspiration. Reset preserves up to ten attempt summaries, including the previous prediction and explanation.

The original **Start an experiment** opens the dilution sandbox. Its default method reaches 50%, 25% and 12.5% stock concentration under instantaneous ideal mixing. Delete the first tip pickup or set a transfer above the teaching model's 300 µL limit to explore failure feedback. This is not a physical mixing model or a specification for every Flex pipette.

## What is included

- Three-step account introduction followed by a five-stage, checkpoint-based novice lesson, equipment glossary, preparation checklist, predictions, step explanations and reflection.
- Labeled equipment illustration and an honest remote-connection status view; the illustration is not live 3D.
- Click/keyboard placement of movable items on a schematic Flex deck. The waste chute is fixed at D3; occupied movable slots swap. This does not validate geometric reachability.
- Editable action sequence, volumes, source/destination, ordering and starting liquid amounts.
- Run, pause, single-step, reset, observations, goal assessment and saved experiments.
- Server-owned state, per-user storage keys and optimistic concurrency checks. Invalid actions produce visible errors without partial transfers.
- AWS Cognito authorization-code/PKCE login; API Gateway validates JWTs and scopes, and Lambda rechecks trusted authorizer claims.
- Private S3 + CloudFront website, API Gateway + FastAPI/Mangum Lambda, DynamoDB, logs, basic error alarm and a scoped optional GitHub OIDC deployment role.
- CI checks and a manual AWS application deployment workflow. No infrastructure is provisioned by a push.

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
| `docs/ARCHITECTURE.md` | State ownership, limitations and design choices |
| `docs/LEARNING-EXPERIENCE.md` | Novice curriculum, target experience and implementation boundaries |
| `docs/REMOTE-UBUNTU.md` | Administrator handoff for connecting the existing Ubuntu host |

The existing Matterix code and asset repositories remain independent. Do not duplicate its physics or robot execution logic here.
