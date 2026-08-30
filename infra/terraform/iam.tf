# Least-privilege IAM policies, one per service, per XC-03 / TSD SS6
# ("least-privilege IAM per service"). These resources only CREATE the
# policy documents — attaching them to a real execution role (ECS task
# role / k8s IRSA role / EC2 instance profile) is left to whoever runs this
# for real, once that role exists (see variables *_execution_role_names
# and README.md). No roles are created here: this module doesn't know
# whether prod runs on ECS or k8s yet (open item, TSD SS10).

data "aws_iam_policy_document" "backend_policy" {
  # backend: write presign only / read metadata (TSD task breakdown XC-03).
  # It issues presigned PutObject URLs for enrollment media and, on
  # `POST .../complete`, does a HEAD/GetObject-class read to validate
  # size/type/checksum (BE-06) — it never reads/writes anything else.
  statement {
    sid    = "PresignEnrollmentUploads"
    effect = "Allow"
    actions = [
      "s3:PutObject",
    ]
    resources = ["${aws_s3_bucket.media.arn}/enrollment/*"]
  }

  statement {
    sid    = "ReadEnrollmentMetadataForValidation"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:GetObjectAttributes",
    ]
    resources = ["${aws_s3_bucket.media.arn}/enrollment/*"]
  }

  statement {
    sid       = "ListBucketEnrollmentPrefixOnly"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.media.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["enrollment/*"]
    }
  }

  statement {
    sid    = "UseMediaKmsKey"
    effect = "Allow"
    actions = [
      "kms:Decrypt",
      "kms:GenerateDataKey",
    ]
    resources = [aws_kms_key.media.arn]
  }
}

resource "aws_iam_policy" "backend" {
  name        = "frac-backend-s3-presign-${var.environment}"
  description = "backend: presign uploads + read metadata under enrollment/ only (least-privilege, TSD SS6)."
  policy      = data.aws_iam_policy_document.backend_policy.json
  tags        = var.tags
}

data "aws_iam_policy_document" "ai_training_policy" {
  # ai-training: read-only (TSD task breakdown XC-03) — reads enrollment
  # media for embedding/QC pipelines and dataset manifests for training runs.
  statement {
    sid    = "ReadMediaAndDatasetsReadOnly"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:GetObjectAttributes",
    ]
    resources = [
      "${aws_s3_bucket.media.arn}/enrollment/*",
      "${aws_s3_bucket.media.arn}/datasets/*",
    ]
  }

  statement {
    sid       = "ListBucketReadOnlyPrefixes"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.media.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["enrollment/*", "datasets/*"]
    }
  }

  statement {
    sid       = "UseMediaKmsKeyDecryptOnly"
    effect    = "Allow"
    actions   = ["kms:Decrypt"]
    resources = [aws_kms_key.media.arn]
  }
}

resource "aws_iam_policy" "ai_training" {
  name        = "frac-ai-training-s3-readonly-${var.environment}"
  description = "ai-training: read-only access to enrollment/ and datasets/ (least-privilege, TSD SS6)."
  policy      = data.aws_iam_policy_document.ai_training_policy.json
  tags        = var.tags
}

data "aws_iam_policy_document" "workers_policy" {
  # workers: read + lifecycle (TSD task breakdown XC-03) — Celery workers
  # doing QC (TR-02), retention automation (BE-14) and revocation/deletion
  # cascade (BE-08) need to read and delete objects and manage retention
  # tags/lifecycle across the whole bucket (they operate on any prefix a
  # user's data can land in).
  statement {
    sid    = "ReadAndManageObjectLifecycle"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:GetObjectAttributes",
      "s3:DeleteObject",
      "s3:DeleteObjectVersion",
      "s3:PutObjectTagging",
      "s3:GetObjectTagging",
    ]
    resources = ["${aws_s3_bucket.media.arn}/*"]
  }

  statement {
    sid       = "ListBucketForWorkers"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.media.arn]
  }

  statement {
    sid    = "UseMediaKmsKey"
    effect = "Allow"
    actions = [
      "kms:Decrypt",
      "kms:GenerateDataKey",
    ]
    resources = [aws_kms_key.media.arn]
  }
}

resource "aws_iam_policy" "workers" {
  name        = "frac-workers-s3-read-lifecycle-${var.environment}"
  description = "workers (QC / retention / deletion cascade): read + lifecycle management across the bucket (least-privilege, TSD SS6)."
  policy      = data.aws_iam_policy_document.workers_policy.json
  tags        = var.tags
}

# --- Optional attachment to existing execution roles ---------------------
# All three lists default to [] (variables.tf), so by default these
# `for_each` blocks create nothing. A human fills them in via
# terraform.tfvars once the real execution roles exist (see README.md).

resource "aws_iam_role_policy_attachment" "backend" {
  for_each   = toset(var.backend_execution_role_names)
  role       = each.value
  policy_arn = aws_iam_policy.backend.arn
}

resource "aws_iam_role_policy_attachment" "ai_training" {
  for_each   = toset(var.ai_training_execution_role_names)
  role       = each.value
  policy_arn = aws_iam_policy.ai_training.arn
}

resource "aws_iam_role_policy_attachment" "workers" {
  for_each   = toset(var.worker_execution_role_names)
  role       = each.value
  policy_arn = aws_iam_policy.workers.arn
}
