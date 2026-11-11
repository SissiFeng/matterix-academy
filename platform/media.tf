# Run-specific KVS signaling channels are created and retired by the control plane.
# Both endpoints use TURN; Ubuntu opens outbound connections only. No GPU/EC2,
# public lab listener, desktop input or cross-region media service is introduced.
locals {
  media_prefix = "${local.name}-sim-"
  media_arn    = "arn:aws:kinesisvideo:${var.region}:${local.suffix}:channel/${local.media_prefix}*/*"
}
resource "aws_iam_role_policy" "viewer_media" {
  name = "run-scoped-viewport-viewer"
  role = aws_iam_role.api.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect   = "Allow"
    Action   = ["kinesisvideo:GetSignalingChannelEndpoint", "kinesisvideo:GetIceServerConfig", "kinesisvideo:ConnectAsViewer"]
    Resource = local.media_arn
  }] })
}
resource "aws_iam_role_policy" "publisher_media" {
  name = "run-scoped-viewport-publisher"
  role = aws_iam_role.worker["worker"].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect   = "Allow"
    Action   = ["kinesisvideo:CreateSignalingChannel", "kinesisvideo:DescribeSignalingChannel", "kinesisvideo:GetSignalingChannelEndpoint", "kinesisvideo:GetIceServerConfig", "kinesisvideo:ConnectAsMaster"]
    Resource = local.media_arn
  }] })
}
resource "aws_iam_role_policy" "reaper_media" {
  name = "retire-run-viewports"
  role = aws_iam_role.worker["reaper"].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect   = "Allow"
    Action   = ["kinesisvideo:CreateSignalingChannel", "kinesisvideo:DescribeSignalingChannel", "kinesisvideo:DeleteSignalingChannel"]
    Resource = local.media_arn
  }] })
}
