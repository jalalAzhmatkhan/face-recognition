variable "aws_region" {
  description = "AWS region for the media bucket and KMS key (e.g. ap-southeast-1)."
  type        = string
}

variable "environment" {
  description = "Deployment environment tag (dev|staging|prod)."
  type        = string
  default     = "dev"
}

variable "bucket_name" {
  description = "Name of the private S3 bucket for enrollment media, event frames, dataset manifests and MLflow artifacts (TSD SS4/SS6). Must be globally unique."
  type        = string
  default     = "frac-media"
}

variable "kms_key_alias" {
  description = "Alias for the customer-managed KMS key used for SSE-KMS on the bucket."
  type        = string
  default     = "alias/frac-media"
}

variable "kms_deletion_window_in_days" {
  description = "Waiting period before the KMS key is deleted if ever destroyed."
  type        = number
  default     = 30
}

variable "raw_media_retention_days" {
  description = "Lifecycle expiry (days) for raw enrollment media under enrollment/ (ASM-10: 90-day retention)."
  type        = number
  default     = 90
}

variable "event_frame_retention_days" {
  description = "Lifecycle expiry (days) for short-retention event frames under events/ (TSD SS4: 'optional retention, short lifecycle')."
  type        = number
  default     = 30
}

variable "noncurrent_version_retention_days" {
  description = "How long to keep noncurrent object versions (bucket versioning is enabled) before they expire."
  type        = number
  default     = 30
}

variable "backend_execution_role_names" {
  description = <<-EOT
    IAM role NAMES (not ARNs — aws_iam_role_policy_attachment takes a name)
    that should get the "backend" policy attached (presigned-URL issuance +
    metadata reads). Left empty by default: this module only CREATES the
    policy, a human attaches it to the real execution role once that role
    exists (ECS task role / k8s IRSA role / EC2 instance role — infra
    decision still open per TSD SS10).
  EOT
  type    = list(string)
  default = []
}

variable "ai_training_execution_role_names" {
  description = "IAM role NAMES that should get the read-only ai-training policy attached (see backend_execution_role_names for why this defaults empty)."
  type        = list(string)
  default     = []
}

variable "worker_execution_role_names" {
  description = "IAM role NAMES that should get the read+lifecycle worker policy attached (see backend_execution_role_names for why this defaults empty)."
  type        = list(string)
  default     = []
}

variable "tags" {
  description = "Extra tags applied to every resource."
  type        = map(string)
  default     = {}
}
