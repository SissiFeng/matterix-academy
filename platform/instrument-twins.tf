# Optional photo-to-twin generation with GPT-6 Astra on Bedrock Mantle. Off by default.
# The Bedrock API key lives in an existing Secrets Manager secret; this module creates
# no secret and never places the key in Terraform state or the Lambda environment.
variable "twin_region" {
  type        = string
  default     = ""
  description = "Bedrock Mantle region serving openai.gpt-6-astra, or empty to disable photo generation."
  validation {
    condition     = contains(["", "us-east-1", "us-west-2"], var.twin_region)
    error_message = "Use us-east-1 or us-west-2, or leave empty."
  }
}
variable "twin_api_key_secret_arn" {
  type        = string
  default     = ""
  description = "ARN of an existing Secrets Manager secret whose SecretString is the Bedrock API key."
  validation {
    condition     = var.twin_api_key_secret_arn == "" || can(regex("^arn:aws:secretsmanager:[a-z0-9-]+:[0-9]{12}:secret:[A-Za-z0-9/_+=.@-]+$", var.twin_api_key_secret_arn))
    error_message = "Use the full secret ARN, not a name, wildcard or key value."
  }
}

resource "aws_iam_role_policy" "twin_secret" {
  count = var.twin_api_key_secret_arn == "" ? 0 : 1
  role  = aws_iam_role.api.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = var.twin_api_key_secret_arn }
  ] })
  lifecycle {
    precondition {
      condition     = var.twin_region != ""
      error_message = "Set twin_region together with twin_api_key_secret_arn."
    }
  }
}
