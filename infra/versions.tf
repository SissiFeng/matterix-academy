terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
  # Use -backend-config with an operator-owned state bucket; see docs/AWS.md.
  backend "s3" {}
}

provider "aws" {
  region              = var.region
  allowed_account_ids = var.expected_account_id == "" ? null : [var.expected_account_id]
  default_tags {
    tags = { Application = "matterix-academy", Environment = var.environment, ManagedBy = "Terraform" }
  }
}

# GPU power/SSM can target a different region from identity and learner data.
provider "aws" {
  alias               = "gpu"
  region              = var.gpu_region != "" ? var.gpu_region : var.region
  allowed_account_ids = var.expected_account_id == "" ? null : [var.expected_account_id]
  default_tags {
    tags = { Application = "matterix-academy", Environment = var.environment, ManagedBy = "Terraform" }
  }
}
