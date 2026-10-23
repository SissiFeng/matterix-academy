terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
  # Deliberately local and separate from infra/. Configure remote state only after approval.
}

provider "aws" {
  region                      = var.region
  allowed_account_ids         = var.enabled ? [var.expected_account_id] : null
  access_key                  = var.enabled ? null : "offline-validation"
  secret_key                  = var.enabled ? null : "offline-validation"
  skip_credentials_validation = !var.enabled
  skip_requesting_account_id  = !var.enabled
  skip_metadata_api_check     = !var.enabled
  skip_region_validation      = !var.enabled
  default_tags {
    tags = {
      Application = "matterix-academy"
      Component   = "ec2-native-pilot"
      ManagedBy   = "Terraform"
    }
  }
}
