terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # No backend block on purpose: state storage/locking (e.g. S3 + DynamoDB)
  # is an infra decision for whoever runs `terraform apply` for real (see
  # README.md "Cara apply"). Configuring a real backend here would make this
  # module silently try to talk to AWS the moment someone runs `terraform
  # init`, which is out of scope for this agent.
}

provider "aws" {
  region = var.aws_region
}
