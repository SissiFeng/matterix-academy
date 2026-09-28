variable "region" {
  type    = string
  default = "ca-central-1"
}
variable "environment" {
  type    = string
  default = "dev"
  validation {
    condition     = contains(["dev", "test", "prod"], var.environment)
    error_message = "Use dev, test or prod."
  }
}
variable "lambda_zip" {
  type    = string
  default = "../build/lambda.zip"
}
variable "github_repository" {
  type    = string
  default = "SissiFeng/matterix-academy"
}
variable "github_oidc_provider_arn" {
  type        = string
  default     = ""
  description = "Existing GitHub OIDC provider ARN. Empty disables the deployment role."
}
variable "github_environment" {
  type    = string
  default = "aws-development"
}

data "aws_caller_identity" "current" {}
locals {
  name   = "matterix-academy-${var.environment}"
  suffix = data.aws_caller_identity.current.account_id
}
