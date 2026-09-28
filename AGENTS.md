# Matterix Academy

- Keep the existing Matterix and assets repositories independent; do not copy their runtime or binaries here.
- Teaching results are synthetic. Never label them as Isaac/GPU, physical robot or chemical validation.
- AWS user identity comes exclusively from the API Gateway JWT authorizer context in the Lambda event. Every data operation is scoped to that subject.
- All session mutations require an expected version. Preserve atomic writes and reject stale commands.
- Local guest access is loopback-only and explicitly enabled. AWS must fail closed when identity settings are incomplete.
- Do not enable a live Matterix UI until the Ubuntu gateway has passed `docs/MATTERIX-CONTRACT.md` qualification.
- Frontend uses React, TypeScript and CSS Modules. Introduce Three.js only for a specific requirement that the schematic or streaming view cannot satisfy.
- Run `bash scripts/build-lambda.sh`, `bash scripts/verify.sh`, and the Playwright journeys for changes affecting execution or user flows.
- Do not create AWS infrastructure or select an AWS account as part of an ordinary code change. The deployment procedure is in `docs/AWS.md`.
