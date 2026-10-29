# AWS deployment

The repository contains a standalone serverless deployment. The AC environment uses the verified SDL0-DEV1 account (`247893369214`) in `ca-central-1`, with an existing encrypted/versioned state bucket and lock table. See [DEPLOYMENT-2026-10-01.md](DEPLOYMENT-2026-10-01.md) for the actual deployment and verification record. Infrastructure definitions alone are not evidence of a deployed service.

## Stack

- S3 private, encrypted, versioned frontend bucket with CloudFront Origin Access Control.
- CloudFront HTTPS frontend and same-origin `/api/*` routing; API responses are never cached. SPA rewriting applies only to frontend paths, so API 401/403 responses remain errors.
- Cognito user pool with configurable email-domain admission and a public browser client using authorization code + PKCE. AC dev admits verified `@utoronto.ca` learners; other deployments default to invitation-only.
- API Gateway HTTP API with JWT authorization and a custom access-token scope.
- Python 3.12 x86_64 Lambda running FastAPI through Mangum; no public Lambda function URL.
- Separate worker HTTP API, zero-cache machine authorizer, worker Lambda and scheduled lease reaper. Workers initiate outbound HTTPS; AWS needs no inbound connection to Ubuntu. Native execution defaults off, and each worker requires operator qualification.
- DynamoDB on-demand table, deletion protection, encryption and point-in-time recovery.
- Scoped service IAM roles, 30-day logs, request throttling, optional Lambda concurrency reservations, and error alarms. The alarm has no notification destination until an operator adds one.
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

5. If using GitHub deployment, set `github_oidc_provider_arn` to the account's existing provider and re-plan/apply. The stack does not create a duplicate provider. Configure GitHub environment `aws-development` to allow `main` only with no manual approval for this automatic development deployment. Check the repository OIDC subject format with `gh api repos/SissiFeng/matterix-academy/actions/oidc/customization/sub`; this repository uses immutable owner/repository IDs, recorded in `github_oidc_subject_prefix`. Set these environment variables from verified Terraform outputs:

| Variable | Source |
|---|---|
| `AWS_ROLE_ARN` | `github_role_arn` |
| `AWS_REGION` | selected region |
| `AWS_ACCOUNT_ID` | verified account ID |
| `WEB_BUCKET` | `frontend_bucket` |
| `DISTRIBUTION_ID` | `distribution_id` |
| `LAMBDA_FUNCTION` | `lambda_function` |
| `WORKER_LAMBDA_FUNCTIONS` | `terraform output -json worker_lambda_functions` (JSON array) |
| `APP_URL` | `app_url` |

6. Every push/merge to `main` automatically starts **Deploy academy to AWS**. Its build job packages and tests the exact commit without AWS credentials, then uploads a checksum-bound release artifact. The separate, serialized deployment job receives short-lived OIDC credentials only after tests pass, publishes that artifact to all four Lambda functions and S3, invalidates CloudFront, and verifies `/version.json`, health and unauthenticated denial. A superseded main commit is skipped before publishing. Manual reruns remain available. The workflow does not run Terraform or create infrastructure. See [CONTINUOUS-DEPLOYMENT.md](CONTINUOUS-DEPLOYMENT.md).
7. In AC dev, register using an actual `@utoronto.ca` mailbox and confirm its email code, or invite a test learner through the Cognito console. Confirm Hosted UI login, first-run onboarding, create/run/reset, refresh persistence and sign-out at the deployed URL. Use two distinct accounts to check isolation. Public health checks alone do not prove login or classroom readiness.

Terraform bootstraps application Lambda code and owns resources, configuration and IAM. The separate Cognito admission Lambda is entirely Terraform-owned, including its deterministic `build/cognito-signup.zip`; application deployment credentials cannot update it. After bootstrap, the workflow owns application code; Terraform ignores `filename`/`source_code_hash` changes so an infrastructure apply cannot silently republish an older local package. For initial publication use the tested release workflow with verified output values. Do not open API CORS broadly; requests use the CloudFront origin. Add a custom hostname only after updating Cognito callback/logout URLs and the application's configured URL together.

## AC environment

### Find Academy in the AWS console

Open CloudFront in account **SDL0-DEV1 / 247893369214**. CloudFront distributions
are global; changing the console's regional selection does not select another
account. Search for distribution **E3UW98EHZSA0FU**, domain
**d2m3yolcjdy6d2.cloudfront.net**, or its configured name
**matterix-academy-dev**. The student interface is branded **Lab Onboarding**;
AWS resource names retain **Matterix Academy**. The
[distribution console](https://console.aws.amazon.com/cloudfront/v4/home#/distributions/E3UW98EHZSA0FU)
and [student site](https://d2m3yolcjdy6d2.cloudfront.net/) point to this deployment.
The console link uses the currently signed-in AWS account; it does not switch
accounts for you.

Terraform sets the distribution's `Name` tag and comment to the same
`matterix-academy-dev` identifier used by AC's blueprint. AWS uses the
[`Name` tag for the distribution name](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/distribution-web-creating-console.html).
Publishing application code does not apply this infrastructure metadata;
review and apply the saved Terraform plan, then verify the name and tags in the
console. Keep the existing distribution ID, origins and state key. If the plan
proposes replacement or unrelated changes, resolve those before applying it.

The account was selected by the user and verified against both Chrome and STS. Authenticate with `aws sso login --profile pas-sdl0-dev`, then use `AWS_PROFILE=pas-sdl0-dev-terraform` for Terraform 1.5.7. This existing profile uses AWS CLI `credential_process` to obtain the refreshed SSO session; direct SSO cache reading by this older Terraform backend failed even though AWS CLI authentication succeeded. No credentials are copied into the repository. `infra/ac-dev.backend.hcl` records the discovered existing state resources and an Academy-only state key; `infra/ac-dev.tfvars.example` pins the expected account and keeps remote execution disabled. Copy the example to ignored `infra/ac-dev.tfvars`, initialize with `-backend-config=ac-dev.backend.hcl`, and plan using `-var-file=ac-dev.tfvars`. Do not alter the shared bucket or lock-table configuration as part of an application deployment.

`remote_execution_enabled=true` requires the native acceptance evidence and operator enrollment described in [WORKER-CONTROL.md](WORKER-CONTROL.md). The account currently has only 10 total Lambda concurrent executions, so AC dev disables reservations (`reserve_lambda_concurrency=false`) and uses a 5 requests/second learner throttle, burst 10. Functions share this capacity with existing account workloads. This is a development environment; raise the quota and qualify capacity before classroom use.

The legacy direct gateway status route is diagnostic only; this deployment does not configure an inbound Ubuntu URL or gateway secret in Lambda.

## Learner registration

AC dev sets `self_signup_email_domains = ["utoronto.ca"]`. On the welcome page, choose **Sign in or create an account**, then **Sign up** in Cognito. Use an email whose domain is exactly `utoronto.ca`, choose a password, and enter the code received at that mailbox. Cognito confirms the account after email verification, so no administrator approval is required. This is email-based registration, not University of Toronto SSO.

The pre-sign-up trigger rejects other domains, subdomains and suffix lookalikes. It never auto-confirms users or auto-verifies email, and client metadata cannot grant a role. Every admitted account receives the existing ordinary learner experience: its own progress and teaching exercises, with no teacher/admin role or native-device access. IAM-authorized operators can still invite external learners through Cognito. The rule controls admission; it does not periodically verify university affiliation or revoke existing accounts. Email changes require verification before replacing the current address.

To suspend new self-registration, set the domain list to `[]`, rebuild with `bash scripts/build-lambda.sh`, and review/apply the Terraform plan. Existing accounts continue to sign in. Change the allowed domains through Terraform only; the public `/api/config` list is a display hint, while Cognito's trigger enforces admission. The trigger role can write only its own logs, and Cognito invocation is restricted to this account and user pool. A trigger failure denies registration.

For verification, local tests cover domain boundaries, untrusted metadata and the welcome screen. Live checks can invoke the policy with synthetic events and reject a disallowed Cognito sign-up. A successful real-mailbox confirmation and two-user isolation exercise still require actual test learners; do not send registration emails to invented university addresses.

References: [Cognito pre-sign-up trigger](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-lambda-pre-sign-up.html), [email confirmation and attribute verification](https://docs.aws.amazon.com/cognito/latest/developerguide/signing-up-users-in-your-app.html).

## Operations and rollback

- DynamoDB stores profiles and experiments durably. A Lambda restart does not lose teaching state. Monitor Lambda errors/throttles, API Gateway errors, DynamoDB throttling and budget alarms before inviting a cohort.
- AC dev operational error/throttle alarms now use a confirmed SNS email destination. Controlled alarm and recovery emails were observed on 2026-10-23. The user canceled the additional US$400 account budget; keep Academy budget creation disabled and preserve the organization's existing budget. Application-scoped budgets require verified payer-side activation of the cost allocation tag.
- Session data is keyed by Cognito subject; never reuse a user identity for multiple students. The first release has no teacher administration UI or cross-user data access.
- Source maps and tokens are not published in diagnostics. Browser access/ID tokens last 60 minutes and are stored in session storage; users sign in again after expiration. Tokens issued before the configuration change retain their old expiration.
- Retain a known-good application commit. For application rollback, rebuild that reviewed commit and publish its Lambda artifact and `index.html`; hashed assets from previous deployments are retained. Infrastructure changes require a separate reviewed Terraform plan.
- Use DynamoDB point-in-time recovery for data incidents, restoring into a separate table and inspecting it before switching the application. Do not destroy/recreate a user pool to fix login.
- Infrastructure teardown is intentionally guarded by table/user-pool deletion protection and a non-empty, versioned S3 bucket. Archive required learner records first and explicitly review removal outside the application release process.
- Local `.data` files, local cookies and local identities are never uploaded to AWS.

## Validation levels

`terraform validate` verifies provider schema and internal references. It does not establish IAM entitlement, regional capacity, account quota, successful apply, OAuth behavior or live service health. Tests use mocked DynamoDB. A real plan/apply and deployed two-user exercise are required before claiming AWS deployment success.

Primary references: [Cognito PKCE authorization](https://docs.aws.amazon.com/cognito/latest/developerguide/authorization-endpoint.html), [API Gateway JWT validation](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-jwt-authorizer.html), [DynamoDB concurrency](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/BestPractices_OptimisticLocking.html), [Isaac Sim streaming](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/manual_livestream_clients.html).

## Prepared single EC2 GPU pilot (not deployed)

The existing pilot can be configured for [on-demand wakeup](DT-WAKEUP.md) using
`gpu_instance_id` and `gpu_worker_id`. This adds power management only; native
qualification and user execution authority remain independently enforced.

The [AC GPU blueprint audit](AC-GPU-BLUEPRINT.md) confirms that AC's shared modules
support ECS on EC2 GPU inputs. Those inputs do not apply to this serverless root.
The current Matterix acceptance uses the dedicated Ubuntu worker below; it does
not replace the student application or take ownership of shared ECS capacity.

The [EC2 GPU pilot plan](EC2-GPU-PILOT.md) adds a separate, default-disabled
Terraform root at `infra/ec2-gpu/`. It reuses the worker API for one fixed native
scene. The ordinary application deployment does not apply it or enable native
execution. Current pricing evidence, image inputs and commissioning/browser
acceptance steps are recorded there. `bash scripts/verify-ec2-gpu.sh` is an
offline zero-resource check; it needs no selected AWS account.
