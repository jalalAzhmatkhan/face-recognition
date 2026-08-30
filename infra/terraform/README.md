# infra/terraform — S3 + IAM + KMS (XC-03)

This directory is **Infrastructure-as-Code only**. It has never been
`terraform apply`'d by an agent, and it must stay that way — provisioning
real AWS resources requires a human with real AWS credentials, which is
explicitly out of scope for the backend-engineer agent that authored this.

## Status: bucket is being provisioned manually — Terraform is a reference

**Update (2026-08-30):** the user has decided to provision the S3 bucket
**manually** (AWS Console / CLI by hand), not through this Terraform module.
This module is kept in the repo as an **optional reference IaC** — it
documents what "least-privilege, SSE-KMS, TLS-only, 90-day lifecycle" should
look like per TSD §4/§6, and can be adopted later (or used as a diff against
whatever gets clicked together by hand) — but running it is no longer the
critical path.

**What actually matters right now:** after the bucket is created manually,
fill in these values in each service's `.env` (copied from `.env.example`,
never commit the real `.env`):

| Value | Where it comes from (manual provisioning) | Goes into |
|---|---|---|
| `AWS_REGION` | Region you created the bucket in (e.g. `ap-southeast-1`) | root `.env`, `backend/.env` |
| `AWS_S3_BUCKET_NAME` | The bucket name you chose | root `.env`, `backend/.env` |
| `AWS_S3_PREFIX` | Folder prefix inside the bucket for this app's objects (e.g. `face-recognition/`) | root `.env`, `backend/.env` |
| `AWS_ACCESS_KEY_ID` | Access key for an IAM user/role scoped to that bucket | root `.env`, `backend/.env` |
| `AWS_SECRET_ACCESS_KEY` | Secret for the same credential | root `.env`, `backend/.env` |

`backend/app/core/config.py` reads these five as `Settings` fields
(`aws_region`, `aws_s3_bucket_name`, `aws_s3_prefix`, `aws_access_key_id`,
`aws_secret_access_key` — the last is a `SecretStr` so it never prints in
logs/repr). `ai-training/src/ai_training/config.py` has the equivalent under
its own `TRN_S3__*` namespace (`TRN_S3__BUCKET`, `TRN_S3__REGION`) and reads
AWS credentials from the standard `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`
env vars directly (boto3's default credential chain), not a `TRN_`-prefixed
duplicate — so the same two env vars work for both services.

Whoever provisions manually should still apply the same security bar this
module encodes, even without running Terraform:
- Block Public Access: **all four settings ON**.
- Versioning: **Enabled**.
- Default encryption: **SSE-KMS** with a customer-managed key (not
  `aws:kms` with the AWS-managed key, and not SSE-S3).
- Bucket policy: **deny non-TLS requests** (`aws:SecureTransport: false` →
  Deny) and deny `PutObject` that doesn't set
  `s3:x-amz-server-side-encryption: aws:kms`.
- Lifecycle rule on `enrollment/*`: expire at **90 days** (ASM-10).
- Lifecycle rule on `events/*`: short expiry (default suggestion: 30 days).
- IAM: separate least-privilege policies per service — see "What this
  module creates" below for the exact statements; replicate them by hand
  (or paste the JSON straight from `terraform plan`/the `.tf` files without
  applying) when creating the manual IAM users/roles.

## What this module creates (if/when someone does apply it)

- `kms.tf` — one customer-managed KMS key (`aws_kms_key.media`) with
  **key rotation enabled**, plus an alias. Key policy grants the account
  root full access and the S3 service `Decrypt`/`GenerateDataKey` scoped to
  this account (so S3 can actually use the key for SSE-KMS).
- `s3.tf` — one private bucket (`aws_s3_bucket.media`, default name
  `frac-media`) with: public access fully blocked, versioning enabled,
  default SSE-KMS encryption via the key above, a bucket policy that denies
  non-TLS requests and unencrypted `PutObject`, and lifecycle rules:
  `enrollment/*` expires after `var.raw_media_retention_days` (default 90,
  per ASM-10), `events/*` expires after `var.event_frame_retention_days`
  (default 30), plus a bucket-wide rule cleaning up noncurrent versions and
  abandoned multipart uploads (`datasets/` and `mlflow/` are intentionally
  never expired — they're not raw media).
- `iam.tf` — three `aws_iam_policy` resources, **not attached to anything by
  default**:
  - `backend` — `s3:PutObject` (presign) + `s3:GetObject`/
    `GetObjectAttributes` (metadata read for upload validation) + scoped
    `ListBucket`, all restricted to `enrollment/*`, plus KMS
    `Decrypt`/`GenerateDataKey` on the media key.
  - `ai_training` — read-only: `GetObject`/`GetObjectAttributes` + scoped
    `ListBucket` on `enrollment/*` and `datasets/*`, plus KMS `Decrypt` only.
  - `workers` — read + lifecycle: `GetObject`, `DeleteObject`/
    `DeleteObjectVersion`, `PutObjectTagging`/`GetObjectTagging`,
    `ListBucket` across the whole bucket, plus KMS
    `Decrypt`/`GenerateDataKey`. For the Celery workers doing QC (TR-02),
    retention automation (BE-14) and the revoke/delete cascade (BE-08).

  To actually attach one of these policies to a role, set the matching
  `*_execution_role_names` variable (a list of **role names**, not ARNs —
  see `variables.tf`) once that role exists. All three default to `[]`, so
  by default this module creates policies but attaches them to nothing.

## Variables you need to fill in (`terraform.tfvars`)

Copy `terraform.tfvars.example` to `terraform.tfvars` (already covered by
`.gitignore` — never commit it) and fill in at minimum `aws_region`. Every
other variable has a sensible default; see `variables.tf` for the full list
and descriptions. **No AWS credentials go in this file** — Terraform (like
boto3) authenticates via the standard AWS credential chain (env vars,
`aws configure`/SSO profile, or an assumed role), configured outside this
repo.

## How to apply this — MANUALLY, by a human, only if you decide to adopt it

This agent never ran `terraform init`/`plan`/`apply` and never will. If a
human decides to pick this module back up instead of managing the bucket by
hand:

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # then edit terraform.tfvars
terraform init      # downloads the aws provider; needs network access
terraform fmt -check
terraform validate
terraform plan -out=tfplan   # review every resource carefully before applying
terraform apply tfplan
```

Prerequisites for that:
- AWS credentials with permission to create S3 buckets, KMS keys, and IAM
  policies (e.g. via `aws configure`, `AWS_PROFILE`, or an assumed role) —
  never hardcode credentials in `.tf`/`.tfvars` files.
- Decide on remote state (e.g. an S3 backend + DynamoDB lock table) before
  the first real `apply` in a shared/team setting — `versions.tf`
  deliberately has no `backend` block configured, so by default state is
  local (`terraform.tfstate`, gitignored) which is fine solo but not for a
  team.
- After `apply`, read the outputs (`bucket_name`, `kms_key_arn`,
  `*_iam_policy_arn`) and, for IAM, attach the printed policy ARNs to the
  real execution roles once those roles exist (see `*_execution_role_names`
  above) — or just fill the `AWS_S3_*`/`AWS_ACCESS_KEY_ID`/
  `AWS_SECRET_ACCESS_KEY` env vars from whatever credential you provision
  for local/CI access, same as the manual-provisioning table above.

## Non-negotiables enforced here (do not weaken without re-reviewing TSD §6)

- Bucket is **always** private (`block_public_acls`/`block_public_policy`/
  `ignore_public_acls`/`restrict_public_buckets` all `true`).
- Encryption is **always** SSE-KMS with a customer-managed key with rotation
  on — never SSE-S3, never the AWS-managed key.
- The bucket policy **always** denies non-TLS requests and unencrypted
  uploads.
- IAM policies are scoped by prefix and by verb per service — nobody gets
  blanket `s3:*`.
