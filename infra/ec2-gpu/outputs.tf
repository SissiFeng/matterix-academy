output "pilot" {
  value = var.enabled ? {
    instance_id = aws_instance.host[0].id
    worker_id   = var.worker_id
    region      = var.region
    } : {
    instance_id = null
    worker_id   = var.worker_id
    region      = var.region
  }
  description = "Provisioning identity only; never native qualification or browser acceptance."
}

output "resources_enabled" {
  value       = var.enabled
  description = "False during preparation. Not the separate application native-execution gate."
}
