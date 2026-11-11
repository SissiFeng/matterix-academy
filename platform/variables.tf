variable "region" {
  type    = string
  default = "ca-central-1"
}
variable "expected_account_id" {
  type        = string
  default     = ""
  description = "Account verified by the operator; nonempty pins provider credentials to that account."
  validation {
    condition     = var.expected_account_id == "" || can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "Expected account ID must have 12 digits."
  }
}
variable "remote_execution_enabled" {
  type        = bool
  default     = false
  description = "Enable only after installed Ubuntu native qualification; worker registry must also be qualified."
}

variable "pairing_enabled" {
  type        = bool
  default     = false
  description = "Enable sim-to-real coordination (simulation workers, device gateways, pair runs)."
}

variable "real_execution_enabled" {
  type        = bool
  default     = false
  description = "Enable operator-approved physical execution. Requires pairing_enabled and a qualified gateway."
}

variable "operator_group" {
  type        = string
  default     = "lab-operators"
  description = "Cognito group whose members may approve physical runs and reconcile instruments."
}

variable "reserve_lambda_concurrency" {
  description = "Enable per-function reservations only when the account quota leaves AWS's required unreserved capacity."
  type        = bool
  default     = false
}

variable "learner_request_rate" {
  description = "Steady learner HTTP API requests per second; size against account Lambda capacity."
  type        = number
  default     = 60
  validation {
    condition     = var.learner_request_rate >= 1 && var.learner_request_rate <= 60
    error_message = "Choose a rate between 1 and 60 requests per second."
  }
}
variable "environment" {
  type    = string
  default = "dev"
  validation {
    condition     = contains(["dev", "test", "prod"], var.environment)
    error_message = "Use dev, test or prod."
  }
}
variable "self_signup_email_domains" {
  type        = set(string)
  default     = []
  description = "Exact lowercase email domains admitted to verified learner self-registration; empty keeps invitation-only access."
  validation {
    condition     = alltrue([for domain in var.self_signup_email_domains : can(regex("^[a-z0-9]+([.-][a-z0-9]+)*\\.[a-z]{2,}$", domain))])
    error_message = "Use exact lowercase email domains, without @, whitespace or wildcards."
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
variable "github_oidc_subject_prefix" {
  type        = string
  default     = ""
  description = "Exact repo subject prefix returned by GitHub's OIDC settings, including immutable owner/repository IDs when enabled."
  validation {
    condition     = var.github_oidc_subject_prefix == "" || can(regex("^repo:[A-Za-z0-9_.@-]+/[A-Za-z0-9_.@-]+$", var.github_oidc_subject_prefix))
    error_message = "Use the exact repo:OWNER/REPOSITORY prefix with optional immutable IDs, without wildcards."
  }
}

data "aws_caller_identity" "current" {}
locals {
  name   = "matterix-academy-${var.environment}"
  suffix = data.aws_caller_identity.current.account_id
}
