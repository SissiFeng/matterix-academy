output "app_url" { value = "https://${aws_cloudfront_distribution.web.domain_name}" }
output "frontend_bucket" { value = aws_s3_bucket.web.id }
output "distribution_id" { value = aws_cloudfront_distribution.web.id }
output "lambda_function" { value = aws_lambda_function.api.function_name }
output "cognito_pool_id" { value = aws_cognito_user_pool.learners.id }
output "github_role_arn" { value = try(aws_iam_role.github_deploy[0].arn, null) }
