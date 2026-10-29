# Sim-to-real coordination: separate credential classes on the machine API.
# Device gateways (/internal/gateway/*) and external orchestrators (/external/*)
# each get their own Lambda authorizer that reads only its own registry.
# Everything stays inert until pairing_enabled / real_execution_enabled are set.
locals {
  sim2real_authorizers = {
    gateway      = { handler = "academy.worker_api.authorize_gateway", registry = "system#gateways", name = "device-gateway-only" }
    orchestrator = { handler = "academy.worker_api.authorize_orchestrator", registry = "system#orchestrators", name = "external-orchestrator-only" }
  }
}

resource "aws_cloudwatch_log_group" "sim2real_authorizer" {
  for_each          = local.sim2real_authorizers
  name              = "/aws/lambda/${local.name}-${each.key}-authorizer"
  retention_in_days = 30
}

resource "aws_iam_role" "sim2real_authorizer" {
  for_each           = local.sim2real_authorizers
  name               = "${local.name}-${each.key}-authorizer"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}

resource "aws_iam_role_policy" "sim2real_authorizer" {
  for_each = local.sim2real_authorizers
  role     = aws_iam_role.sim2real_authorizer[each.key].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.sim2real_authorizer[each.key].arn}:*" },
    { Effect = "Allow", Action = ["dynamodb:GetItem"], Resource = aws_dynamodb_table.records.arn, Condition = { "ForAllValues:StringEquals" = { "dynamodb:LeadingKeys" = [each.value.registry] } } }
  ] })
}

resource "aws_lambda_function" "sim2real_authorizer" {
  # Terraform bootstraps code; the tested GitHub release owns later code updates.
  lifecycle { ignore_changes = [filename, source_code_hash] }
  for_each                       = local.sim2real_authorizers
  function_name                  = "${local.name}-${each.key}-authorizer"
  role                           = aws_iam_role.sim2real_authorizer[each.key].arn
  runtime                        = "python3.12"
  architectures                  = ["x86_64"]
  handler                        = each.value.handler
  filename                       = var.lambda_zip
  source_code_hash               = filebase64sha256(var.lambda_zip)
  timeout                        = 5
  memory_size                    = 256
  reserved_concurrent_executions = var.reserve_lambda_concurrency ? 3 : -1
  environment {
    variables = {
      ACADEMY_RUNTIME        = "aws"
      ACADEMY_TABLE          = aws_dynamodb_table.records.name
      ACADEMY_REMOTE_ENABLED = tostring(var.remote_execution_enabled)
      ACADEMY_REAL_ENABLED   = tostring(var.real_execution_enabled)
    }
  }
  depends_on = [aws_iam_role_policy.sim2real_authorizer, aws_cloudwatch_log_group.sim2real_authorizer]
}

resource "aws_apigatewayv2_authorizer" "sim2real" {
  for_each                          = local.sim2real_authorizers
  api_id                            = aws_apigatewayv2_api.worker.id
  authorizer_type                   = "REQUEST"
  authorizer_uri                    = aws_lambda_function.sim2real_authorizer[each.key].invoke_arn
  identity_sources                  = ["$request.header.Authorization"]
  name                              = each.value.name
  authorizer_payload_format_version = "2.0"
  enable_simple_responses           = true
  authorizer_result_ttl_in_seconds  = 0
}

resource "aws_lambda_permission" "sim2real_authorizer" {
  for_each      = local.sim2real_authorizers
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.sim2real_authorizer[each.key].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.worker.execution_arn}/authorizers/${aws_apigatewayv2_authorizer.sim2real[each.key].id}"
}

# More specific than ANY /internal/{proxy+}: gateway credentials never reach the
# simulation-worker authorizer, and simulation credentials never reach this one.
resource "aws_apigatewayv2_route" "gateway" {
  api_id             = aws_apigatewayv2_api.worker.id
  route_key          = "ANY /internal/gateway/{proxy+}"
  target             = "integrations/${aws_apigatewayv2_integration.worker.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.sim2real["gateway"].id
}

resource "aws_apigatewayv2_route" "orchestrator" {
  api_id             = aws_apigatewayv2_api.worker.id
  route_key          = "ANY /external/{proxy+}"
  target             = "integrations/${aws_apigatewayv2_integration.worker.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.sim2real["orchestrator"].id
}

resource "aws_cognito_user_group" "operators" {
  name         = var.operator_group
  user_pool_id = aws_cognito_user_pool.learners.id
  description  = "Lab operators: approve physical runs, reconcile holds and review calibration"
}
