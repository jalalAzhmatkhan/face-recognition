# Customer-managed KMS key for SSE-KMS on the media bucket (TSD SS6:
# "At rest: S3 SSE-KMS (customer-managed key)"). Key rotation enabled per
# XC-03 requirement.

data "aws_caller_identity" "current" {}

resource "aws_kms_key" "media" {
  description             = "CMK for SSE-KMS on the ${var.bucket_name} media bucket (face-recognition biometric data)."
  deletion_window_in_days = var.kms_deletion_window_in_days
  enable_key_rotation     = true

  policy = data.aws_iam_policy_document.kms_key_policy.json

  tags = merge(var.tags, {
    Environment = var.environment
    Project     = "face-recognition"
  })
}

resource "aws_kms_alias" "media" {
  name          = var.kms_key_alias
  target_key_id = aws_kms_key.media.key_id
}

# Root account keeps full admin control (required so the key is never
# accidentally locked out); actual data-plane usage (Encrypt/Decrypt/
# GenerateDataKey) is granted separately to each service's IAM policy below,
# not blanket-granted here.
data "aws_iam_policy_document" "kms_key_policy" {
  statement {
    sid    = "EnableRootAccountFullAccess"
    effect = "Allow"
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
    actions   = ["kms:*"]
    resources = ["*"]
  }

  statement {
    sid    = "AllowS3ServiceToUseKey"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["s3.amazonaws.com"]
    }
    actions = [
      "kms:Decrypt",
      "kms:GenerateDataKey",
    ]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}
