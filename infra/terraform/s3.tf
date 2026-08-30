# Private S3 bucket for enrollment media, event frames, dataset manifests
# and MLflow artifacts (TSD SS4 "S3 layout" / SS6 "Security & Privacy Design").
#
# Layout (informational — objects are written by the app, not by Terraform):
#   enrollment/{user_id}/{session_id}/photo_{n}.jpg
#   enrollment/{user_id}/{session_id}/rotation.webm
#   events/{yyyy}/{mm}/{device_id}/{event_id}.jpg   (short retention)
#   datasets/{snapshot_id}/manifest.json
#   mlflow/ (artifacts)

resource "aws_s3_bucket" "media" {
  bucket = var.bucket_name

  tags = merge(var.tags, {
    Environment = var.environment
    Project     = "face-recognition"
    DataClass   = "biometric-sensitive" # UU PDP 27/2022 sensitive personal data (TSD SS6)
  })
}

# Block ALL public access — bucket is private only, presigned URLs are the
# sole write/read path from outside AWS (NFR-SEC-02).
resource "aws_s3_bucket_public_access_block" "media" {
  bucket = aws_s3_bucket.media.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "media" {
  bucket = aws_s3_bucket.media.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "media" {
  bucket = aws_s3_bucket.media.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.media.arn
    }
    # Reduces KMS API calls/cost; safe for our access pattern (NFR-SEC-02).
    bucket_key_enabled = true
  }
}

# TLS-only bucket policy (deny any request that is not over HTTPS) — TSD SS6
# "In transit: TLS 1.2+ everywhere".
data "aws_iam_policy_document" "media_bucket_policy" {
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    actions   = ["s3:*"]
    resources = [
      aws_s3_bucket.media.arn,
      "${aws_s3_bucket.media.arn}/*",
    ]
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  statement {
    sid    = "DenyUnencryptedObjectUploads"
    effect = "Deny"
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.media.arn}/*"]
    condition {
      test     = "StringNotEquals"
      variable = "s3:x-amz-server-side-encryption"
      values   = ["aws:kms"]
    }
  }
}

resource "aws_s3_bucket_policy" "media" {
  bucket = aws_s3_bucket.media.id
  policy = data.aws_iam_policy_document.media_bucket_policy.json

  # Public access block + policy attach both target the same bucket; avoid a
  # race where the policy is attached before PAB settings apply.
  depends_on = [aws_s3_bucket_public_access_block.media]
}

# Lifecycle: ASM-10 (90-day raw media retention) + short retention for event
# frames + cleanup of abandoned multipart uploads and noncurrent versions
# (bucket versioning is on, so old versions would otherwise accumulate
# forever and undermine the "media doesn't linger" intent).
resource "aws_s3_bucket_lifecycle_configuration" "media" {
  bucket = aws_s3_bucket.media.id

  rule {
    id     = "raw-media-90d"
    status = "Enabled"
    filter {
      prefix = "enrollment/"
    }
    expiration {
      days = var.raw_media_retention_days
    }
  }

  rule {
    id     = "event-frames-short-retention"
    status = "Enabled"
    filter {
      prefix = "events/"
    }
    expiration {
      days = var.event_frame_retention_days
    }
  }

  # Bucket-wide housekeeping (no prefix filter — applies to enrollment/,
  # events/, datasets/ and mlflow/ alike): datasets/ (versioned manifests,
  # not media copies) and mlflow/ (experiment artifacts) are intentionally
  # NOT expired above — they are not raw media and ASM-10 doesn't apply —
  # but noncurrent versions and abandoned multipart uploads are still
  # cleaned up everywhere to control storage cost. Kept as its own rule
  # (rather than duplicated into the two rules above) so there's exactly one
  # place controlling this and no risk of conflicting per-prefix values.
  rule {
    id     = "bucket-wide-housekeeping"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_version_retention_days
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}
