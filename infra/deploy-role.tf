resource "aws_iam_role" "github_deploy" {
  count = var.github_oidc_provider_arn != "" ? 1 : 0
  name  = "${local.name}-github-deploy"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Allow", Principal = { Federated = var.github_oidc_provider_arn }, Action = "sts:AssumeRoleWithWebIdentity",
    Condition = { StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com", "token.actions.githubusercontent.com:sub" = "${var.github_oidc_subject_prefix != "" ? var.github_oidc_subject_prefix : "repo:${var.github_repository}"}:environment:${var.github_environment}" } }
  }] })
}
resource "aws_iam_role_policy" "github_deploy" {
  count = var.github_oidc_provider_arn != "" ? 1 : 0
  role  = aws_iam_role.github_deploy[0].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["s3:ListBucket"], Resource = aws_s3_bucket.web.arn },
    { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject"], Resource = "${aws_s3_bucket.web.arn}/*" },
    { Effect = "Allow", Action = ["lambda:UpdateFunctionCode", "lambda:GetFunction", "lambda:GetFunctionConfiguration"], Resource = concat([aws_lambda_function.api.arn], [for item in aws_lambda_function.worker : item.arn]) },
    { Effect = "Allow", Action = ["cloudfront:CreateInvalidation", "cloudfront:GetInvalidation"], Resource = aws_cloudfront_distribution.web.arn }
  ] })
}
