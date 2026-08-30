output "bucket_name" {
  description = "S3 bucket name — set as AWS_S3_BUCKET_NAME in backend/.env and TRN_S3__BUCKET in ai-training/.env."
  value       = aws_s3_bucket.media.bucket
}

output "bucket_arn" {
  value = aws_s3_bucket.media.arn
}

output "kms_key_arn" {
  description = "Customer-managed KMS key ARN used for SSE-KMS on the bucket."
  value       = aws_kms_key.media.arn
}

output "kms_key_alias" {
  value = aws_kms_alias.media.name
}

output "backend_iam_policy_arn" {
  description = "Attach to the backend service's execution role (presign + metadata read, enrollment/ only)."
  value       = aws_iam_policy.backend.arn
}

output "ai_training_iam_policy_arn" {
  description = "Attach to the ai-training service's execution role (read-only, enrollment/ + datasets/)."
  value       = aws_iam_policy.ai_training.arn
}

output "workers_iam_policy_arn" {
  description = "Attach to worker/Celery execution roles (read + lifecycle, whole bucket)."
  value       = aws_iam_policy.workers.arn
}
