# Automatic application deployment

A push or merged pull request to `main` starts **Deploy academy to AWS**. Local edits, `git pull`, and feature-branch pushes do not publish the website. Pull requests run **Verify academy**. The release URL remains https://d2m3yolcjdy6d2.cloudfront.net.

## Release sequence

1. A build job without AWS credentials installs locked dependencies, builds the Linux Lambda archive, runs the project verification suite and Chromium journeys, and builds the frontend.
2. `scripts/release.py manifest` binds the Git commit, workflow run, Lambda checksum and every frontend file checksum. The tested files are uploaded as an immutable GitHub artifact. Artifact names include the run attempt; rebuilding a failed run creates a new artifact, while rerunning only deployment reuses the successful build's artifact name.
3. The deployment job is serialized with `cancel-in-progress: false`. While holding this slot, it compares its commit with the current `main` head. A superseded commit is skipped before AWS authentication. An in-progress publication is allowed to finish; a newer successful release follows it.
4. The `aws-development` environment admits only the **main branch**, with no manual reviewer gate for this development deployment. A short-lived OIDC session assumes `matterix-academy-dev-github-deploy` in account `247893369214`. There are no stored AWS access keys. This repository's exact immutable OIDC subject prefix is pinned in Terraform, including owner/repository IDs.
5. Before writing, the publisher checks the release checksums, AWS account and all four functions' disabled native-execution flags. It updates and verifies all four Lambda code hashes, uploads hashed static assets, then the frontend entry page and `/version.json`.
6. CloudFront invalidation completes before the job checks the public homepage, health, exact release manifest and unauthenticated denial. The GitHub job summary identifies the deployed commit and site. A green build alone is not a successful deployment.

The visible release record is [version.json](https://d2m3yolcjdy6d2.cloudfront.net/version.json). It contains commit and checksums, never credentials or learner records.

## Ownership and permissions

Terraform owns infrastructure, configuration, native-execution flags and IAM. It bootstraps Lambda code on creation, then ignores `filename` and `source_code_hash`: the release workflow owns subsequent application code. Infrastructure changes still require an explicit reviewed Terraform plan/apply. The deployment role cannot change IAM, Cognito, Lambda environment configuration, DynamoDB records, or other applications. Its permissions cover only the four Academy function code updates, this web bucket's objects and this distribution's invalidations.

The existing account-wide GitHub OIDC provider is reused. The environment's main-only rule is part of the authorization boundary because the OIDC subject identifies the environment. Do not broaden its deployment branches without reviewing AWS trust.

The current account has only 10 total Lambda concurrent executions. This pipeline does not raise quotas or demonstrate classroom capacity. Native execution, GPU and real devices remain disabled/unqualified.

## Failures and recovery

- Failed lint, tests, build or checksum checks prevent publication. Inspect the failing step and its browser artifact; fix the source and merge the correction.
- Lambda and S3 updates are sequential, not a globally atomic transaction. A cloud error midway can leave a partial application update. Keep changes compatible across that window. Rerun the failed deployment job to publish the same tested artifact; the GitHub summary is only successful after all checks finish.
- If the source must be rolled back, revert the faulty commit on `main` and let the new tested commit deploy. Manually replaying an obsolete commit is deliberately skipped by the main-head check.
- If infrastructure must be rolled back, review a Terraform plan independently. Application release credentials cannot destroy or reconfigure infrastructure.
- Artifacts are retained for 14 days. Older releases can be rebuilt from their source, but rollback uses a new main commit and receives fresh verification.

Implementation verification: 200 backend tests and 23 Chromium journeys passed locally; actionlint accepted both workflows. The previously intermittent navigation journey now waits for save completion instead of treating the busy-disabled button as a save receipt. A scoped Terraform apply created only the GitHub deployment role and its resource-scoped policy. See the task's final delivery record for hosted CI and first automatic deployment evidence.

References: [GitHub OIDC in AWS](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws), [deployment branch policies](https://docs.github.com/en/rest/deployments/branch-policies), [workflow concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).
