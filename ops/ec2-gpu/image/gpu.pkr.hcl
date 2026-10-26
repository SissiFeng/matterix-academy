packer {
  required_version = "= 1.16.1"
  required_plugins {
    amazon = {
      source  = "github.com/hashicorp/amazon"
      version = "= 1.8.3"
    }
  }
}
variable "confirm_paid_build" {
  type    = bool
  default = false
  validation {
    condition     = var.confirm_paid_build
    error_message = "Image builds create paid EC2/EBS resources. Explicit build authorization is required."
  }
}
variable "accept_nvidia_eula" {
  type    = bool
  default = false
  validation {
    condition     = var.accept_nvidia_eula
    error_message = "The operator must accept the NVIDIA software licenses before installation."
  }
}
variable "region" {
  type    = string
  default = "ca-central-1"
}
variable "build_instance_type" {
  type    = string
  default = "g6.4xlarge"
  validation {
    condition     = contains(["g5.2xlarge", "g6.2xlarge", "g6.4xlarge", "g6e.2xlarge"], var.build_instance_type)
    error_message = "Use a full A10G/L4/L40S single-GPU commissioning candidate; native probes and qualification remain required."
  }
}
variable "expected_account_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "Use the explicitly authorized account."
  }
}
variable "source_ami" {
  type = string
  validation {
    condition     = can(regex("^ami-[a-f0-9]+$", var.source_ami))
    error_message = "Pin a reviewed Ubuntu 24.04 x86_64 base AMI; no latest lookup is used."
  }
}
variable "subnet_id" { type = string }
variable "vpc_id" { type = string }
variable "ssh_cidr" {
  type = string
  validation {
    condition     = can(regex("^[0-9.]+/32$", var.ssh_cidr))
    error_message = "Temporary build SSH is restricted to the operator's single IPv4 address."
  }
}
variable "input_dir" {
  type        = string
  description = "Protected external directory prepared by ec2-gpu-release.py and ec2-gpu-sources.py."
}
variable "release_sha256" {
  type = string
  validation {
    condition     = can(regex("^[a-f0-9]{64}$", var.release_sha256))
    error_message = "Use the release.json archive digest."
  }
}
variable "manifest_sha256" {
  type = string
  validation {
    condition     = can(regex("^[a-f0-9]{64}$", var.manifest_sha256))
    error_message = "Use the image-manifest.json digest."
  }
}
source "amazon-ebs" "internal_flex" {
  region                                = var.region
  source_ami                            = var.source_ami
  instance_type                         = var.build_instance_type
  subnet_id                             = var.subnet_id
  vpc_id                                = var.vpc_id
  associate_public_ip_address           = true
  ssh_username                          = "ubuntu"
  ssh_timeout                           = "20m"
  temporary_security_group_source_cidrs = [var.ssh_cidr]
  ami_name                              = "academy-internal-flex-${substr(var.release_sha256, 0, 12)}-${formatdate("YYYYMMDDhhmmss", timestamp())}"
  ami_description                       = "Internal Flex browser DT commissioning candidate; not qualified"
  encrypt_boot                          = true
  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }
  launch_block_device_mappings {
    device_name           = "/dev/sda1"
    volume_size           = 300
    volume_type           = "gp3"
    delete_on_termination = true
    encrypted             = true
  }
  tags = {
    Application           = "matterix-academy"
    Environment           = "dev"
    ManagedBy             = "packer"
    AcademyManifestSHA256 = var.manifest_sha256
    AcademyReleaseSHA256  = var.release_sha256
    AcademyQualification  = "prepared-not-qualified"
    Purpose               = "internal-flex-browser-dt"
    AcademyBuildAccount   = var.expected_account_id
    AcademyBuildInstance  = var.build_instance_type
  }
  run_tags = {
    Application = "matterix-academy"
    Environment = "dev"
    ManagedBy   = "packer"
    Purpose     = "academy-image-build"
  }
  run_volume_tags = {
    Application = "matterix-academy"
    Environment = "dev"
    ManagedBy   = "packer"
    Purpose     = "academy-image-build"
  }
}
build {
  sources = ["source.amazon-ebs.internal_flex"]
  provisioner "shell" { inline = ["mkdir -p /tmp/academy-image-input && chmod 700 /tmp/academy-image-input"] }
  provisioner "file" {
    source      = "${var.input_dir}/academy.tar.gz"
    destination = "/tmp/academy-image-input/academy.tar.gz"
  }
  provisioner "file" {
    source      = "${var.input_dir}/release.json"
    destination = "/tmp/academy-image-input/release.json"
  }
  provisioner "file" {
    source      = "${var.input_dir}/image-manifest.json"
    destination = "/tmp/academy-image-input/image-manifest.json"
  }
  provisioner "file" {
    source      = "${var.input_dir}/engine.tar.gz"
    destination = "/tmp/academy-image-input/engine.tar.gz"
  }
  provisioner "file" {
    source      = "${var.input_dir}/assets.tar.gz"
    destination = "/tmp/academy-image-input/assets.tar.gz"
  }
  provisioner "file" {
    source      = "${var.input_dir}/sources.json"
    destination = "/tmp/academy-image-input/sources.json"
  }
  provisioner "file" {
    source      = "${var.input_dir}/nvidia-driver.run"
    destination = "/tmp/academy-image-input/nvidia-driver.run"
  }
  provisioner "file" {
    source      = "${var.input_dir}/driver.json"
    destination = "/tmp/academy-image-input/driver.json"
  }
  provisioner "shell" {
    script            = "${path.root}/provision.sh"
    environment_vars  = ["RELEASE_SHA256=${var.release_sha256}", "MANIFEST_SHA256=${var.manifest_sha256}"]
    execute_command   = "chmod +x {{ .Path }}; {{ .Vars }} sudo -E bash '{{ .Path }}'"
    expect_disconnect = true
  }
  provisioner "shell" {
    pause_before    = "30s"
    script          = "${path.root}/finalize.sh"
    execute_command = "chmod +x {{ .Path }}; sudo bash '{{ .Path }}'"
  }
  post-processor "manifest" {
    output     = "${var.input_dir}/packer-manifest.json"
    strip_path = true
  }
}
