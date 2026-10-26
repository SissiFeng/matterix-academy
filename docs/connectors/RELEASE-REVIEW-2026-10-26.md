# Student trial release review — 2026-10-26

[PR #10](https://github.com/SissiFeng/matterix-academy/pull/10) integrates the
connector setup page and the shared UI simplification. Review fixes cover:

- Exact S3-validated SHA-256 checks before signing either package download.
- Explicit Apple Silicon / Intel selection and theme-aware setup markers.
- Clearing a rejected run only after a definite rejection and confirmed absence;
  uncertain submissions retain their identity across refresh.
- One bounded stop of the exact robot run after authority loss or deadline expiry,
  followed by unknown-outcome reconciliation. Expired preflight cannot start motion.
- Explicit revoked-credential rotation, TLS certificate validation, and probe
  freshness checks that reject future timestamps.
- Bounded ZIP metadata parsing and archive path counts including implicit parents.
  TAR decompression and PAX/GNU metadata reads have separate bounded budgets.
  Failed unjournaled installation staging can be retried; journaled unknown
  attempts cannot be replayed.
- Private artifact publication rejects both modern CloudFront service principals
  and legacy origin access identities. Manual reviewed publication is independent
  of the scheduled intake toggle.

Each behavior has focused regression coverage where it affects runtime state,
authorization, downloads, extraction, publication or browser recovery. Full
Lambda, project verification and browser results are attached to the exact PR
revision in GitHub Actions. Local fixture results do not establish live hardware
or native Matterix acceptance.

## IAM finding not applied

The proposed `dynamodb:TransactWriteItems` IAM action is not required.
`DynamoStore.transact` emits `Put` and `Delete` operations, and the companion role
already grants table-scoped `PutItem` and `DeleteItem`. AWS documents that
transaction permissions use the underlying item actions. Conditional expressions
on those writes do not add a separate `ConditionCheck` operation.
See [AWS: IAM with DynamoDB transactions](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis-iam.html).

## Publication boundary

The ordinary application pipeline updates the existing four Lambda functions and
website. It does not enable the optional companion API, publish an approved Mac
installer, provision GPU capacity or authorize physical execution. The catalog
remains empty of approved packages. The current published revision is recorded
in the site's [version manifest](https://d2m3yolcjdy6d2.cloudfront.net/version.json).
