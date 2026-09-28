# Matterix Academy

A browser-based learning lab for students to arrange a Flex deck, compose liquid-handling steps, make mistakes and understand the result. React + TypeScript and FastAPI, with independently deployable AWS infrastructure.

**Current release:** a working teaching model for a three-stage serial dilution. It is explicitly synthetic: no physical robot, GPU physics, collision checks or chemical predictions are connected. The Matterix gateway has a qualification client and a documented integration contract; live sessions remain disabled until an Ubuntu implementation is connected and tested.

## Run locally

Requirements: Node.js 22.12+, Python 3.12 and [uv](https://docs.astral.sh/uv/).

```sh
bash scripts/dev.sh
```

Open [the learning lab](http://127.0.0.1:5173). The API listens on loopback port 8000. Local sign-in creates a signed, HttpOnly, 24-hour guest cookie. Its data persists in `.data/academy.sqlite`; this is a local preview identity, not a replacement for a production account. Signing out ends access to that guest identity. No passwords, AWS credentials or Matterix installation are needed for the preview.

Use the default method to reach 50%, 25% and 12.5% stock concentration. Delete the first tip pickup or set a transfer above 300 µL to explore failure feedback. Reset restores every modeled liquid and consumable state while preserving up to ten attempt summaries.

## What is included

- Three-step onboarding and a course workspace.
- Click/keyboard placement and drag/drop of four supported labware items on a schematic Flex deck. Occupied slots swap; this does not validate geometric reachability.
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
| `app/backend/academy/gateway.py` | Qualification client for the proposed Ubuntu gateway contract |
| `infra` | Standalone Terraform AWS stack |
| `docs/AWS.md` | Bootstrap, deployment, operations and rollback |
| `docs/MATTERIX-CONTRACT.md` | Integration boundary and required qualification |
| `docs/ARCHITECTURE.md` | State ownership, limitations and design choices |

The existing Matterix code and asset repositories remain independent. Do not duplicate its physics or robot execution logic here.
