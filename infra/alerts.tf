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
  description = "Monthly cost budget for this application's tagged resources. 0 disables the budget."
  validation {
    condition     = var.monthly_budget_usd >= 0
    error_message = "Budget must be zero or positive."
  }
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
  cost_filter {
    name   = "TagKeyValue"
    values = ["user:Application$matterix-academy"]
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
