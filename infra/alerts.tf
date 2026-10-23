# Optional operator notifications. Both default off, so existing plans are unchanged until an
# operator sets them and reviews the plan. Email subscriptions must be confirmed by the recipient.
variable "alarm_email" {
  type        = string
  default     = ""
  description = "Operator email that receives Lambda error alarms and budget alerts. Empty disables notifications."
  validation {
    condition     = var.alarm_email == "" || can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.alarm_email))
    error_message = "Use a single email address or leave empty."
  }
}
variable "monthly_budget_usd" {
  type        = number
  default     = 0
  description = "Monthly cost alert threshold in USD, scoped by budget_scope. This does not stop resources. 0 disables the budget."
  validation {
    condition     = var.monthly_budget_usd >= 0
    error_message = "Budget must be zero or positive."
  }
}

variable "budget_scope" {
  type        = string
  default     = "application"
  description = "application requires the payer to activate the Application cost tag; account conservatively includes all linked-account charges."
  validation {
    condition     = contains(["application", "account"], var.budget_scope)
    error_message = "Choose application or account."
  }
}

variable "application_cost_tag_active" {
  type        = bool
  default     = false
  description = "Set only after verifying the Application cost allocation tag is active in the payer account."
}

# CloudWatch cannot publish to a topic encrypted with the AWS-managed SNS key; alarm payloads
# carry no learner data. Use a customer-managed key with a CloudWatch grant if policy requires.
resource "aws_sns_topic" "alerts" {
  count = var.alarm_email == "" ? 0 : 1
  name  = "${local.name}-alerts"
}
resource "aws_sns_topic_subscription" "alerts_email" {
  count     = var.alarm_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alerts[0].arn
  protocol  = "email"
  endpoint  = var.alarm_email
}
data "aws_iam_policy_document" "alerts" {
  count = var.alarm_email == "" ? 0 : 1
  statement {
    sid       = "CloudWatchAlarms"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts[0].arn]
    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}
resource "aws_sns_topic_policy" "alerts" {
  count  = var.alarm_email == "" ? 0 : 1
  arn    = aws_sns_topic.alerts[0].arn
  policy = data.aws_iam_policy_document.alerts[0].json
}
locals {
  alarm_actions = aws_sns_topic.alerts[*].arn
}

resource "aws_budgets_budget" "monthly" {
  count        = var.monthly_budget_usd > 0 && var.alarm_email != "" ? 1 : 0
  name         = "${local.name}-monthly"
  budget_type  = "COST"
  limit_amount = format("%.2f", var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"
  dynamic "cost_filter" {
    for_each = var.budget_scope == "application" ? [1] : []
    content {
      name   = "TagKeyValue"
      values = ["user:Application$matterix-academy"]
    }
  }
  lifecycle {
    precondition {
      condition     = var.budget_scope == "account" || var.application_cost_tag_active
      error_message = "Verify and activate the Application cost tag with the payer, or use conservative account-wide cost alerts."
    }
  }
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alarm_email]
  }
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alarm_email]
  }
}

locals {
  monitored_functions = merge(
    { api = aws_lambda_function.api.function_name },
    { for key, function in aws_lambda_function.worker : key => function.function_name },
    { signup = aws_lambda_function.signup.function_name }
  )
}

resource "aws_cloudwatch_metric_alarm" "lambda_throttles" {
  for_each            = local.monitored_functions
  alarm_name          = "${local.name}-${each.key}-throttles"
  alarm_description   = "Lambda rejected an invocation due to concurrency limits. Check shared account capacity before increasing request rates."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Throttles"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  dimensions          = { FunctionName = each.value }
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "gateway_errors" {
  for_each            = { learner = aws_apigatewayv2_api.api.id, worker = aws_apigatewayv2_api.worker.id }
  alarm_name          = "${local.name}-${each.key}-gateway-errors"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "5xx"
  namespace           = "AWS/ApiGateway"
  period              = 300
  statistic           = "Sum"
  threshold           = 5
  treat_missing_data  = "notBreaching"
  dimensions          = { ApiId = each.value }
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "database_throttles" {
  for_each            = toset(["ReadThrottleEvents", "WriteThrottleEvents"])
  alarm_name          = "${local.name}-database-${each.value}"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = each.value
  namespace           = "AWS/DynamoDB"
  period              = 300
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  dimensions          = { TableName = aws_dynamodb_table.records.name }
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

output "alarm_topic_arn" { value = try(aws_sns_topic.alerts[0].arn, null) }
output "monthly_budget_scope" { value = length(aws_budgets_budget.monthly) > 0 ? var.budget_scope : null }
