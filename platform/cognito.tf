# Admission policy code stays Terraform-owned, outside the app release role.
resource "aws_cloudwatch_log_group" "signup" {
  name              = "/aws/lambda/${local.name}-signup"
  retention_in_days = 30
}

resource "aws_iam_role" "signup" {
  name               = "${local.name}-signup"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}

resource "aws_iam_role_policy" "signup" {
  role = aws_iam_role.signup.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.signup.arn}:*" }
  ] })
}

resource "aws_lambda_function" "signup" {
  function_name    = "${local.name}-signup"
  role             = aws_iam_role.signup.arn
  runtime          = "python3.12"
  architectures    = ["x86_64"]
  handler          = "pre_signup.handler"
  filename         = "${path.module}/../build/cognito-signup.zip"
  source_code_hash = filebase64sha256("${path.module}/../build/cognito-signup.zip")
  timeout          = 5
  memory_size      = 128
  environment {
    variables = { SELF_SIGNUP_EMAIL_DOMAINS = jsonencode(var.self_signup_email_domains) }
  }
  depends_on = [aws_iam_role_policy.signup, aws_cloudwatch_log_group.signup]
}

resource "aws_lambda_permission" "signup" {
  statement_id   = "CognitoPreSignUp"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.signup.function_name
  principal      = "cognito-idp.amazonaws.com"
  source_arn     = aws_cognito_user_pool.learners.arn
  source_account = data.aws_caller_identity.current.account_id
}
