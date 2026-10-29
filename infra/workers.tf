# Machine routes have their own API, authorizer and concurrency. They are not
# forwarded through the student CDN and accept no Cognito credentials.
locals {
  worker_functions = {
    worker     = { handler = "academy.worker_api.handler", concurrency = 5, timeout = 15 }
    authorizer = { handler = "academy.worker_api.authorize", concurrency = 3, timeout = 5 }
    reaper     = { handler = "academy.worker_api.reap_handler", concurrency = 1, timeout = 30 }
  }
}
resource "aws_cloudwatch_log_group" "worker" {
  for_each          = local.worker_functions
  name              = "/aws/lambda/${local.name}-${each.key}"
  retention_in_days = 30
}
resource "aws_iam_role" "worker" {
  for_each           = local.worker_functions
  name               = "${local.name}-${each.key}"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}
resource "aws_iam_role_policy" "worker" {
  for_each = local.worker_functions
  role     = aws_iam_role.worker[each.key].id
  policy = jsonencode({ Version = "2012-10-17", Statement = concat([
    { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.worker[each.key].arn}:*" }
    ], [for name in [each.key] :
    { Effect = "Allow", Action = ["dynamodb:GetItem"], Resource = aws_dynamodb_table.records.arn, Condition = { "ForAllValues:StringEquals" = { "dynamodb:LeadingKeys" = ["system#workers"] } } }
    if name == "authorizer"], [for name in [each.key] :
    { Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem", "dynamodb:Query"], Resource = aws_dynamodb_table.records.arn }
  if name != "authorizer"]) })
}
resource "aws_lambda_function" "worker" {
  # Terraform bootstraps code; the tested GitHub release owns later code updates.
  lifecycle { ignore_changes = [filename, source_code_hash] }
  for_each                       = local.worker_functions
  function_name                  = "${local.name}-${each.key}"
  role                           = aws_iam_role.worker[each.key].arn
  runtime                        = "python3.12"
  architectures                  = ["x86_64"]
  handler                        = each.value.handler
  filename                       = var.lambda_zip
  source_code_hash               = filebase64sha256(var.lambda_zip)
  timeout                        = each.value.timeout
  memory_size                    = 256
  reserved_concurrent_executions = var.reserve_lambda_concurrency ? each.value.concurrency : -1
  environment {
    variables = {
      ACADEMY_RUNTIME            = "aws"
      ACADEMY_TABLE              = aws_dynamodb_table.records.name
      ACADEMY_REMOTE_ENABLED     = tostring(var.remote_execution_enabled)
      ACADEMY_MEDIA_PREFIX       = local.media_prefix
      ACADEMY_GPU_REGION         = local.gpu_region
      ACADEMY_GPU_INSTANCE_ID    = each.key != "authorizer" ? var.gpu_instance_id : ""
      ACADEMY_GPU_WORKER_ID      = each.key != "authorizer" ? var.gpu_worker_id : ""
      ACADEMY_GPU_START_DOCUMENT = each.key != "authorizer" && var.gpu_instance_id != "" ? aws_ssm_document.gpu_start[0].name : ""
      ACADEMY_PAIRING_ENABLED    = tostring(var.pairing_enabled)
      ACADEMY_REAL_ENABLED       = tostring(var.real_execution_enabled)
      ACADEMY_POLL_WAIT_S        = "8"
    }
  }
  depends_on = [aws_iam_role_policy.worker, aws_cloudwatch_log_group.worker]
}
resource "aws_apigatewayv2_api" "worker" {
  name          = "${local.name}-worker"
  protocol_type = "HTTP"
}
resource "aws_apigatewayv2_integration" "worker" {
  api_id                 = aws_apigatewayv2_api.worker.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.worker["worker"].invoke_arn
  payload_format_version = "2.0"
}
resource "aws_apigatewayv2_authorizer" "worker" {
  api_id                            = aws_apigatewayv2_api.worker.id
  authorizer_type                   = "REQUEST"
  authorizer_uri                    = aws_lambda_function.worker["authorizer"].invoke_arn
  identity_sources                  = ["$request.header.Authorization"]
  name                              = "registered-machine-only"
  authorizer_payload_format_version = "2.0"
  enable_simple_responses           = true
  authorizer_result_ttl_in_seconds  = 0
}
resource "aws_apigatewayv2_route" "worker" {
  api_id             = aws_apigatewayv2_api.worker.id
  route_key          = "ANY /internal/{proxy+}"
  target             = "integrations/${aws_apigatewayv2_integration.worker.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.worker.id
}
resource "aws_cloudwatch_log_group" "worker_gateway" {
  name              = "/aws/apigateway/${local.name}-worker"
  retention_in_days = 30
}
resource "aws_apigatewayv2_stage" "worker" {
  api_id      = aws_apigatewayv2_api.worker.id
  name        = "$default"
  auto_deploy = true
  default_route_settings {
    throttling_burst_limit = 20
    throttling_rate_limit  = 10
  }
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.worker_gateway.arn
    format          = jsonencode({ requestId = "$context.requestId", status = "$context.status", route = "$context.routeKey", latency = "$context.responseLatency" })
  }
}
resource "aws_lambda_permission" "worker_api" {
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.worker["worker"].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.worker.execution_arn}/*/*"
}
resource "aws_lambda_permission" "worker_authorizer" {
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.worker["authorizer"].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.worker.execution_arn}/authorizers/${aws_apigatewayv2_authorizer.worker.id}"
}
resource "aws_cloudwatch_event_rule" "lease_expiry" {
  name                = "${local.name}-lease-expiry"
  schedule_expression = "rate(1 minute)"
}
resource "aws_cloudwatch_event_target" "lease_expiry" {
  rule = aws_cloudwatch_event_rule.lease_expiry.name
  arn  = aws_lambda_function.worker["reaper"].arn
}
resource "aws_lambda_permission" "lease_expiry" {
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.worker["reaper"].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.lease_expiry.arn
}
resource "aws_cloudwatch_metric_alarm" "worker_errors" {
  for_each            = local.worker_functions
  alarm_name          = "${local.name}-${each.key}-errors"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 5
  treat_missing_data  = "notBreaching"
  dimensions          = { FunctionName = aws_lambda_function.worker[each.key].function_name }
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}
