variable "enabled" {
  description = "Explicit paid-resource opt-in. Keep false during preparation."
  type        = bool
  default     = false
}
variable "region" {
  type    = string
  default = "ca-central-1"
  validation {
    condition     = contains(["ca-central-1", "us-east-1"], var.region)
    error_message = "This pilot was evaluated only in ca-central-1 and us-east-1."
  }
}
variable "expected_account_id" {
  type    = string
  default = ""
  validation {
    condition     = var.expected_account_id == "" || can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "Supply an explicitly approved 12-digit account before enabling."
  }
}
variable "instance_type" {
  type    = string
  default = "g6.4xlarge"
  validation {
    condition     = contains(["g6.2xlarge", "g6.4xlarge", "g6e.2xlarge"], var.instance_type)
    error_message = "Choose one of the evaluated single-GPU candidates."
  }
}
variable "vpc_id" {
  type    = string
  default = ""
}
variable "subnet_id" {
  description = "Existing public subnet with an Internet Gateway route; no NAT is created."
  type        = string
  default     = ""
}
variable "prepared_ami_id" {
  description = "Operator-built, version-pinned Ubuntu x86_64 AMI; never a floating latest lookup."
  type        = string
  default     = ""
}
variable "prepared_ami_owner" {
  description = "Approved image publisher account, normally the deployment account."
  type        = string
  default     = ""
}
variable "image_manifest_sha256" {
  description = "Hash of the reviewed image manifest; also required as the AMI AcademyManifestSHA256 tag."
  type        = string
  default     = ""
}
variable "worker_api_url" {
  description = "Existing machine API, not the learner API. No token or query string."
  type        = string
  default     = ""
  validation {
    condition     = var.worker_api_url == "" || can(regex("^https://[a-z0-9-]+\\.execute-api\\.[a-z0-9-]+\\.amazonaws\\.com$", var.worker_api_url))
    error_message = "Use the existing HTTPS machine API origin without credentials or path."
  }
}
variable "worker_id" {
  type    = string
  default = "ec2-flex-pilot-1"
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,63}$", var.worker_id))
    error_message = "Worker ID must match the existing registry's machine-name format."
  }
}
variable "root_volume_gib" {
  type    = number
  default = 300
  validation {
    condition     = var.root_volume_gib >= 300 && var.root_volume_gib <= 500 && floor(var.root_volume_gib) == var.root_volume_gib
    error_message = "Allocate 300–500 GiB for the image, caches, assets and durable journal."
  }
}
variable "expires_on" {
  description = "Operator review date YYYY-MM-DD. This tag is not an automatic stop mechanism."
  type        = string
  default     = ""
}
