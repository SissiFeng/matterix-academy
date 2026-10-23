data "aws_subnet" "host" {
  count = var.enabled ? 1 : 0
  id    = var.subnet_id
}
data "aws_ami" "prepared" {
  count       = var.enabled ? 1 : 0
  owners      = [var.prepared_ami_owner]
  most_recent = false
  filter {
    name   = "image-id"
    values = [var.prepared_ami_id]
  }
  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
  filter {
    name   = "state"
    values = ["available"]
  }
  filter {
    name   = "tag:AcademyManifestSHA256"
    values = [var.image_manifest_sha256]
  }
}

resource "aws_security_group" "host" {
  count       = var.enabled ? 1 : 0
  name_prefix = "academy-gpu-pilot-"
  description = "Outbound worker only; no SSH, desktop, or raw Isaac streaming ingress"
  vpc_id      = var.vpc_id
  # No ingress. HTTPS covers the machine API, SSM, asset fetch and KVS signaling.
  egress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  # KVS TURN uses UDP 443; peer traffic stays on the authenticated relay.
  egress {
    from_port   = 443
    to_port     = 443
    protocol    = "udp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
resource "aws_iam_role" "host" {
  count       = var.enabled ? 1 : 0
  name_prefix = "academy-gpu-pilot-"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}
resource "aws_iam_role_policy_attachment" "ssm" {
  count      = var.enabled ? 1 : 0
  role       = aws_iam_role.host[0].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}
resource "aws_iam_instance_profile" "host" {
  count       = var.enabled ? 1 : 0
  name_prefix = "academy-gpu-pilot-"
  role        = aws_iam_role.host[0].name
}
resource "aws_instance" "host" {
  count                                = var.enabled ? 1 : 0
  ami                                  = data.aws_ami.prepared[0].id
  instance_type                        = var.instance_type
  subnet_id                            = data.aws_subnet.host[0].id
  vpc_security_group_ids               = [aws_security_group.host[0].id]
  iam_instance_profile                 = aws_iam_instance_profile.host[0].name
  associate_public_ip_address          = true
  instance_initiated_shutdown_behavior = "stop"
  # Cloud-init runs only on first boot. Reject an unreviewed endpoint/unit change
  # through prevent_destroy instead of silently leaving the old host configuration.
  user_data_replace_on_change = true
  user_data = templatefile("${path.module}/cloud-init.yaml.tftpl", {
    unit_b64       = filebase64("${path.module}/../../ops/ec2-gpu/academy-native.service")
    worker_api_url = var.worker_api_url
  })
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
    http_protocol_ipv6          = "disabled"
    instance_metadata_tags      = "disabled"
  }
  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_gib
    encrypted             = true
    iops                  = 3000
    throughput            = 125
    delete_on_termination = false
    tags                  = { Name = "academy-native-retained-root", Evidence = "simulation-only" }
  }
  tags = {
    Name      = "academy-gpu-pilot"
    WorkerId  = var.worker_id
    ExpiresOn = var.expires_on
    Evidence  = "simulation-only"
  }
  lifecycle {
    # Destroy/replacement requires an explicit reviewed change, preserving run journals.
    prevent_destroy = true
    precondition {
      condition     = can(regex("^[0-9]{12}$", var.expected_account_id)) && can(regex("^[0-9]{12}$", var.prepared_ami_owner))
      error_message = "Approved deployment and image-publisher accounts are required."
    }
    precondition {
      condition     = can(regex("^ami-[a-f0-9]{8,17}$", var.prepared_ami_id)) && can(regex("^[a-f0-9]{64}$", var.image_manifest_sha256))
      error_message = "An exact prepared AMI and reviewed manifest hash are required."
    }
    precondition {
      condition     = data.aws_subnet.host[0].vpc_id == var.vpc_id && var.worker_api_url != "" && can(regex("^[0-9]{4}-[0-9]{2}-[0-9]{2}$", var.expires_on))
      error_message = "Confirm the existing subnet/VPC, machine API and pilot review date."
    }
    precondition {
      condition     = !(var.region == "ca-central-1" && var.instance_type == "g6e.2xlarge")
      error_message = "No Canadian G6e price was found in the captured catalog; re-evaluate before enabling it here."
    }
  }
  depends_on = [aws_iam_role_policy_attachment.ssm]
}
