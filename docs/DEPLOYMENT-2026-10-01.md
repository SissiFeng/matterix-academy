# AC development deployment — 2026-10-01

Verified at 2026-10-01T16:04:31.880132+00:00. AWS account **SDL0-DEV1 / 247893369214**, region **ca-central-1**, explicitly selected by the user and matched between Chrome and STS. Deployment used Terraform 1.5.7 and the locked AWS provider 6.66.0.

## Live resources

| Item | Verified value |
|---|---|
| Academy | [https://d2m3yolcjdy6d2.cloudfront.net](https://d2m3yolcjdy6d2.cloudfront.net) |
| Worker API | `https://1cpkmq930k.execute-api.ca-central-1.amazonaws.com` |
| CloudFront distribution | `E3UW98EHZSA0FU`, Deployed |
| Frontend bucket | `matterix-academy-dev-247893369214-web` |
| DynamoDB | `matterix-academy-dev` |
| Cognito pool | `ca-central-1_iW4e6efus` |
| Native execution | **false** |

The saved plan created **54 resources, changed 0, destroyed 0**. The apply completed successfully. A subsequent `terraform plan -detailed-exitcode` returned **0 / No changes**. Existing shared bucket and lock-table settings were not changed. No GPU, EC2, NAT, TURN, ECS, ALB, robot connection or custom domain was created.

Terraform state is at `s3://247893369214-terraform-state/matterix-academy/dev/terraform.tfstate`, using the existing `paper-attribution-terraform-locks` lock table. State bucket encryption, versioning and public-access blocks were checked before deployment. Credentials remain outside the repository. The Terraform profile `pas-sdl0-dev-terraform` delegates to the AWS CLI refreshed SSO credentials through credential_process.

## Published artifacts

All four functions are Active with LastUpdateStatus=Successful, and their AWS CodeSha256 matches the locally built Lambda archive:

- `matterix-academy-dev`
- `matterix-academy-dev-worker`
- `matterix-academy-dev-authorizer`
- `matterix-academy-dev-reaper`

Archive SHA-256: `4ad46026af51175940ae32faf08318438125dea58fac41fd4ea223611e59ad8f`.

Thirteen frontend files were published, with immutable caching for hashed assets and no-cache for index.html. The CloudFront invalidation completed. Chrome displayed the deployed homepage and the Cognito login page with the expected callback, custom scope and S256 PKCE request. No learner password was entered.

Source baseline: `89d38477275cc5855ce2332f11bcb3e897939251` on `codex/flex-guided-learning`, **plus this task's uncommitted deployment/worker changes**. This is a local publication; no new Git commit, push, PR, GitHub environment configuration or CI deployment was performed. The source edits must be committed before treating the baseline hash alone as reproducible release source. During closeout another active task staged product-branding changes in this shared checkout, including the FastAPI display title. Those newer edits are not assumed to be part of this deployment. The published Lambda archive and frontend manifest identify the actual release; all new worker/control-plane modules match the archive. At that initial publication, the optional OIDC role was still unconfigured. A subsequent change adds automatic main-branch publication; see [CONTINUOUS-DEPLOYMENT.md](CONTINUOUS-DEPLOYMENT.md). This section records the earlier manual release, not the later automated release.

## Verification evidence

| Check | Result and boundary |
|---|---|
| `bash scripts/build-lambda.sh` | Passed; deployable Linux x86_64 artifact built |
| `bash scripts/verify.sh` | Passed: **194 backend tests**, lint/format, frontend TypeScript/build, Terraform format/validate |
| `npm run test:e2e` | **23 Chromium journeys passed**, including disabled native entry and synthetic snapshot disconnect/reload |
| Live HTTP checks | Homepage/health 200; learner unauthenticated/forged identity 401; missing worker credential 401; wrong credential 403 |
| Real machine authorization | Temporary unqualified worker authenticated with 200; native claim denied 403; browser Origin denied 403; its credential could not authenticate the learner API; revocation immediately denied 403 |
| Real Lambda + DynamoDB | Saved session persisted; another synthetic subject got 404; stale version got 409; native submit stayed 503 |
| Real DynamoDB transactions | Stale conditional transaction rolled back all writes and retained original version |
| Reaper invocation | Successful, zero expired runs; no native worker was registered |
| Protection checks | All frontend S3 public-access blocks on; DynamoDB deletion protection and PITR on; all native flags false |
| Post-apply plan | No changes, exit 0 |

The cloud smoke script made **21 assertions**. Its learner Lambda invocations intentionally supplied **synthetic authorizer context under the operator's InvokeFunction permission**. They establish deployed handler/IAM/storage behavior; they do **not** establish Cognito token issuance, real student login, or two real learners' end-to-end isolation. All records and temporary machine credentials created by the smoke script were removed. No worker was marked natively qualified.

The backend and browser tests use synthetic native-looking fixtures. No native Matterix, Isaac/GPU, physical device, chemical validation, streaming or classroom throughput acceptance occurred.

Local evidence is retained in ignored `build/`: `verify-deployment.log`, `package-deployment.log`, `playwright-deployment.log`, `terraform-plan.json`, `terraform-apply.log`, `terraform-post-deploy.log`, `terraform-outputs.json`, `published-files.json`, `cloud-smoke.json`, `cloud-runtime.json`, and `academy-deployed.png`. Do not publish Terraform state or credential files with a report.

Re-run the scoped cloud smoke checks only against the intended development account:

```sh
AWS_PROFILE=pas-sdl0-dev AWS_DEFAULT_REGION=ca-central-1 \
  uv run python scripts/smoke-aws.py \
  --outputs build/terraform-outputs.json \
  --expected-account-id 247893369214 \
  --report build/cloud-smoke.json
```

## Remaining acceptance

- The user supplies the first Academy invitation email, then completes Cognito's password/login flow. Run onboarding, save/refresh, teaching execution and sign-out in the deployed app; use a second real account to prove end-to-end isolation. The AWS console identity is not an Academy learner account.
- The native host operator supplies installed Matterix/assets versions and gateway access, then completes [WORKER-CONTROL.md](WORKER-CONTROL.md) and [MATTERIX-CONTRACT.md](MATTERIX-CONTRACT.md) acceptance. Native stays off until then. Streaming needs separate implementation and qualification.
- This account's total Lambda concurrency quota is **10**. AC dev uses shared concurrency (no reservations) and learner throttling of 5 requests/second, burst 10; the machine endpoint remains throttled at 10/second, burst 20. Existing account workloads share the quota. Increase quota, restore reservations and measure capacity before a cohort. AWS documents the required unreserved headroom in [reserved concurrency](https://docs.aws.amazon.com/lambda/latest/dg/configuration-concurrency.html).
- Error alarms exist without a notification destination. An operator must attach the intended notification channel and budget before production operations.

The dedicated worker authorizer uses the [HTTP API Lambda authorizer 2.0 contract](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-lambda-authorizer.html) with zero cache. The deployment uses an existing [S3 Terraform backend](https://developer.hashicorp.com/terraform/language/backend/s3) and a distinct Academy state key.
