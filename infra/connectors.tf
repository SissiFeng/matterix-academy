# Optional: reviewed separately from normal Academy releases. No resources by default.
# Robot/SSH secrets remain on the lab computer, never in Terraform or Lambda.
variable "connector_companion_enabled" {
  type        = bool
  default     = false
  description = "Create a dedicated outbound companion API after deployment review."
}
variable "connector_real_execution_enabled" {
  type        = bool
  default     = false
  description = "Global physical gate; exact native proof, release, local operator and device qualification are also mandatory."
}
variable "connector_artifact_bucket" {
  type        = string
  default     = ""
  description = "Existing, reviewed private artifact bucket. Do not use the CloudFront web bucket. This module creates no bucket."
  validation {
    condition     = var.connector_artifact_bucket == "" || can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.connector_artifact_bucket))
    error_message = "Use a bucket name, not a URL, ARN, path or wildcard."
  }
}

resource "aws_iam_role_policy" "connector_downloads" {
  count = var.connector_artifact_bucket == "" ? 0 : 1
  role  = aws_iam_role.api.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["s3:GetObject"], Resource = "arn:aws:s3:::${var.connector_artifact_bucket}/connectors/approved/*" }
  ] })
  lifecycle {
    precondition {
      condition     = var.connector_artifact_bucket != aws_s3_bucket.web.id
      error_message = "Connector downloads must not share the public website distribution bucket."
    }
  }
}
resource "aws_cloudwatch_log_group" "companion" {
  count             = var.connector_companion_enabled ? 1 : 0
  name              = "/aws/lambda/${local.name}-companion"
  retention_in_days = 14
}
resource "aws_iam_role" "companion" {
  count              = var.connector_companion_enabled ? 1 : 0
  name               = "${local.name}-companion"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}
resource "aws_iam_role_policy" "companion" {
  count = var.connector_companion_enabled ? 1 : 0
  role  = aws_iam_role.companion[0].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.companion[0].arn}:*" },
    { Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem", "dynamodb:Query"], Resource = aws_dynamodb_table.records.arn }
  ] })
}
resource "aws_lambda_function" "companion" {
  count                          = var.connector_companion_enabled ? 1 : 0
  function_name                  = "${local.name}-companion"
  role                           = aws_iam_role.companion[0].arn
  runtime                        = "python3.12"
  architectures                  = ["x86_64"]
  handler                        = "academy.companion_api.handler"
  filename                       = var.lambda_zip
  source_code_hash               = filebase64sha256(var.lambda_zip)
  timeout                        = 15
  memory_size                    = 256
  reserved_concurrent_executions = var.reserve_lambda_concurrency ? 3 : -1
  environment {
    variables = {
      ACADEMY_RUNTIME                = "aws"
      ACADEMY_TABLE                  = aws_dynamodb_table.records.name
      ACADEMY_CONNECTOR_REAL_ENABLED = tostring(var.connector_real_execution_enabled)
    }
  }
  depends_on = [aws_iam_role_policy.companion]
}
resource "aws_apigatewayv2_api" "companion" {
  count         = var.connector_companion_enabled ? 1 : 0
  name          = "${local.name}-companion"
  protocol_type = "HTTP"
}
resource "aws_apigatewayv2_integration" "companion" {
  count                  = var.connector_companion_enabled ? 1 : 0
  api_id                 = aws_apigatewayv2_api.companion[0].id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.companion[0].invoke_arn
  payload_format_version = "2.0"
}
resource "aws_apigatewayv2_route" "companion" {
  count     = var.connector_companion_enabled ? 1 : 0
  api_id    = aws_apigatewayv2_api.companion[0].id
  route_key = "ANY /companion/{proxy+}"
  target    = "integrations/${aws_apigatewayv2_integration.companion[0].id}"
  # Single-use pairing code bootstraps a distinct bearer credential. The dedicated
  # Lambda verifies it on every call, denies browser origins and exposes no user API.
}
resource "aws_apigatewayv2_stage" "companion" {
  count       = var.connector_companion_enabled ? 1 : 0
  api_id      = aws_apigatewayv2_api.companion[0].id
  name        = "$default"
  auto_deploy = true
  default_route_settings {
    throttling_burst_limit = 10
    throttling_rate_limit  = 5
  }
}
resource "aws_lambda_permission" "companion" {
  count         = var.connector_companion_enabled ? 1 : 0
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.companion[0].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.companion[0].execution_arn}/*/*"
}
output "connector_companion_url" {
  value       = var.connector_companion_enabled ? aws_apigatewayv2_api.companion[0].api_endpoint : null
  description = "Exact outbound companion origin to distribute in the reviewed installer configuration."
}
