# Power management for one existing GPU. Does not create/replace a GPU or qualify it.
variable "gpu_region" {
  description = "EC2/SSM region only; blank uses the application's region. Identity and learner data stay put."
  type        = string
  default     = ""
  validation {
    condition     = var.gpu_region == "" || contains(["ca-central-1", "us-east-1", "us-east-2"], var.gpu_region)
    error_message = "Use a GPU region that infra/ec2-gpu and the image build also allow."
  }
}
variable "gpu_instance_id" {
  type    = string
  default = ""
  validation {
    condition     = var.gpu_instance_id == "" || can(regex("^i-[a-f0-9]{17}$", var.gpu_instance_id))
    error_message = "Pin one existing EC2 instance ID, or leave power management disabled."
  }
}
variable "gpu_worker_id" {
  type    = string
  default = "ec2-flex-pilot-1"
}
resource "aws_ssm_document" "gpu_start" {
  provider      = aws.gpu
  count         = var.gpu_instance_id != "" ? 1 : 0
  name          = "${local.name}-start-native"
  document_type = "Command"
  content = jsonencode({
    schemaVersion = "2.2"
    description   = "Start only the installed Academy simulation service; accepts no parameters"
    mainSteps = [{ action = "aws:runShellScript", name = "startNative", inputs = {
      timeoutSeconds = "90"
      runCommand     = ["set -eu", "systemctl start academy-imds.service", "systemctl start academy-native.service", "systemctl is-active --quiet academy-native.service"]
    } }]
  })
}
locals {
  gpu_region = var.gpu_region != "" ? var.gpu_region : var.region
  gpu_arn    = "arn:aws:ec2:${local.gpu_region}:${local.suffix}:instance/${var.gpu_instance_id}"
}
resource "aws_iam_role_policy" "gpu_control" {
  for_each = var.gpu_instance_id != "" ? {
    api = aws_iam_role.api.id, reaper = aws_iam_role.worker["reaper"].id
  } : {}
  role = each.value
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["ec2:DescribeInstances"], Resource = "*", Condition = { StringEquals = { "aws:RequestedRegion" = local.gpu_region } } },
    { Effect = "Allow", Action = ["ec2:StartInstances", "ec2:StopInstances"], Resource = local.gpu_arn },
    { Effect = "Allow", Action = ["ssm:SendCommand"], Resource = [local.gpu_arn, aws_ssm_document.gpu_start[0].arn] },
    { Effect = "Allow", Action = ["ssm:GetCommandInvocation"], Resource = "*", Condition = { StringEquals = { "aws:RequestedRegion" = local.gpu_region } } }
  ] })
}
