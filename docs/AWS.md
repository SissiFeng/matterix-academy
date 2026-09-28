# AWS deployment

The repository contains a standalone deployment; it does not assume the Acceleration Consortium shared infrastructure has been installed. No AWS resources have been provisioned by creating this repository.

## Stack

- S3 private, encrypted, versioned frontend bucket with CloudFront Origin Access Control.
- CloudFront HTTPS frontend and same-origin `/api/*` routing; API responses are never cached. SPA rewriting applies only to frontend paths, so API 401/403 responses remain errors.
- Cognito invitation-only user pool and public browser client using authorization code + PKCE.
- API Gateway HTTP API with JWT authorization and a custom access-token scope.
- Python 3.12 x86_64 Lambda running FastAPI through Mangum; no public Lambda function URL.
- DynamoDB on-demand table, deletion protection, encryption and point-in-time recovery.
- Scoped service IAM role, 30-day logs, request throttling, Lambda concurrency cap, and an error alarm. The alarm has no notification destination until an operator adds one.
- Optional GitHub deployment role with OIDC trust restricted to this repository and one protected environment.

Default region: `ca-central-1`. AWS charges apply when provisioned; calculate costs for the intended classroom load. No GPU instance, VPN, media relay, custom domain or real robot is created by this stack.

## Bootstrap

1. Select the AWS account and region, authenticate with your usual AWS SSO/operator role, and verify the account yourself. Do not commit credentials.
2. Create/reuse an encrypted, versioned Terraform state bucket with public access blocked. For Terraform 1.5.7 use an existing DynamoDB lock table (`LockID`, string partition key). Keep state credentials outside repository files.
3. Install Node 22.12+, Python 3.12, uv, AWS CLI and Terraform 1.5+. Build the Lambda artifact:

```sh
uv sync --frozen
bash scripts/build-lambda.sh
```

4. Initialize the backend using actual state resource names:

```sh
terraform -chdir=infra init -reconfigure \
  -backend-config="bucket=YOUR_STATE_BUCKET" \
  -backend-config="key=matterix-academy/dev/terraform.tfstate" \
  -backend-config="region=ca-central-1" \
  -backend-config="encrypt=true" \
  -backend-config="dynamodb_table=YOUR_STATE_LOCK_TABLE"
cp infra/dev.tfvars.example infra/dev.tfvars
terraform -chdir=infra plan -var-file=dev.tfvars -out=academy.tfplan
```

Review the saved plan and account before applying it. This is a billable infrastructure operation:

```sh
terraform -chdir=infra apply academy.tfplan
terraform -chdir=infra output
```

5. If using GitHub deployment, set `github_oidc_provider_arn` to the account's existing provider and re-plan/apply. The stack does not create a duplicate provider. Configure GitHub environment `aws-development` to allow `main` only and require the appropriate reviewers before deployment. Set these environment variables from verified Terraform outputs:

| Variable | Source |
|---|---|
| `AWS_ROLE_ARN` | `github_role_arn` |
| `AWS_REGION` | selected region |
| `WEB_BUCKET` | `frontend_bucket` |
| `DISTRIBUTION_ID` | `distribution_id` |
| `LAMBDA_FUNCTION` | `lambda_function` |
| `APP_URL` | `app_url` |

6. Run the manual **Deploy academy to AWS** workflow on `main`. It rebuilds, tests, uploads Lambda code and static assets, waits for deployment, invalidates the entry page, and checks public health. It does not run Terraform or create infrastructure.
7. Invite a test learner through the Cognito console. Confirm Hosted UI login, first-run onboarding, create/run/reset, refresh persistence and sign-out at the deployed URL. Use two distinct accounts to check isolation. Public health checks alone do not prove login or classroom readiness.

For direct initial publication after a reviewed plan, use the same upload commands as the deploy workflow with verified output values. Do not open API CORS broadly; requests use the CloudFront origin. Add a custom hostname only after updating Cognito callback/logout URLs and the application's configured URL together.

## Operations and rollback

- DynamoDB stores profiles and experiments durably. A Lambda restart does not lose teaching state. Monitor Lambda errors/throttles, API Gateway errors, DynamoDB throttling and budget alarms before inviting a cohort.
- The error alarm exists without an SNS destination. Attach an operator-owned notification channel and set an account budget before production use.
- Session data is keyed by Cognito subject; never reuse a user identity for multiple students. The first release has no teacher administration UI or cross-user data access.
- Source maps and tokens are not published in diagnostics. Browser tokens are short-lived and stored in session storage; users sign in again after expiration.
- Retain a known-good application commit. For application rollback, rebuild that reviewed commit and publish its Lambda artifact and `index.html`; hashed assets from previous deployments are retained. Infrastructure changes require a separate reviewed Terraform plan.
- Use DynamoDB point-in-time recovery for data incidents, restoring into a separate table and inspecting it before switching the application. Do not destroy/recreate a user pool to fix login.
- Infrastructure teardown is intentionally guarded by table/user-pool deletion protection and a non-empty, versioned S3 bucket. Archive required learner records first and explicitly review removal outside the application release process.
- Local `.data` files, local cookies and local identities are never uploaded to AWS.

## Validation levels

`terraform validate` verifies provider schema and internal references. It does not establish IAM entitlement, regional capacity, account quota, successful apply, OAuth behavior or live service health. Tests use mocked DynamoDB. A real plan/apply and deployed two-user exercise are required before claiming AWS deployment success.

Primary references: [Cognito PKCE authorization](https://docs.aws.amazon.com/cognito/latest/developerguide/authorization-endpoint.html), [API Gateway JWT validation](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-jwt-authorizer.html), [DynamoDB concurrency](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/BestPractices_OptimisticLocking.html), [Isaac Sim streaming](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/manual_livestream_clients.html).
