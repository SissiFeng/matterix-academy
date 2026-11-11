# Optional drafting of described workflows with an Amazon Nova model. Off by default.
# The API Lambda calls the model through its own role; no API key is stored.
variable "brief_model" {
  type        = string
  default     = ""
  description = "Amazon Nova cross-region inference profile ID, for example us.amazon.nova-pro-v1:0, or empty to disable drafting."
  validation {
    condition     = var.brief_model == "" || can(regex("^(us|ca|eu|apac|global)\\.amazon\\.nova-[a-z0-9.-]+:[0-9]+$", var.brief_model))
    error_message = "Use an Amazon Nova inference profile ID, or leave empty."
  }
}
variable "brief_region" {
  type        = string
  default     = ""
  description = "Region whose Bedrock runtime serves brief_model."
}

locals {
  # A us. profile routes each request to one of these regions' foundation model.
  brief_routes     = { us = ["us-east-1", "us-east-2", "us-west-2"] }
  brief_prefix     = var.brief_model == "" ? "" : split(".", var.brief_model)[0]
  brief_foundation = var.brief_model == "" ? "" : join(".", slice(split(".", var.brief_model), 1, length(split(".", var.brief_model))))
}

resource "aws_iam_role_policy" "brief_model" {
  count = var.brief_model == "" ? 0 : 1
  role  = aws_iam_role.api.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    {
      Effect   = "Allow"
      Action   = ["bedrock:InvokeModel"]
      Resource = "arn:aws:bedrock:${var.brief_region}:${data.aws_caller_identity.current.account_id}:inference-profile/${var.brief_model}"
    },
    {
      Effect = "Allow"
      Action = ["bedrock:InvokeModel"]
      Resource = [
        for region in lookup(local.brief_routes, local.brief_prefix, [var.brief_region]) :
        "arn:aws:bedrock:${region}::foundation-model/${local.brief_foundation}"
      ]
      # Only through the inference profile, never the foundation model directly.
      Condition = { StringLike = { "bedrock:InferenceProfileArn" = "arn:aws:bedrock:${var.brief_region}:${data.aws_caller_identity.current.account_id}:inference-profile/${var.brief_model}" } }
    },
  ] })
  lifecycle {
    precondition {
      condition     = var.brief_region != ""
      error_message = "Set brief_region together with brief_model."
    }
  }
}
