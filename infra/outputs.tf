output "cloud_run_url" {
  description = "LeadBot API Cloud Run URL"
  value       = google_cloud_run_v2_service.leadbot_api.uri
}

output "artifact_registry" {
  description = "Docker image registry"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/leadbot"
}

output "workload_identity_provider" {
  description = "Workload Identity Provider for GitHub Actions"
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "cicd_service_account" {
  description = "CI/CD service account email"
  value       = google_service_account.leadbot_cicd.email
}

output "cloud_sql_instance" {
  description = "Cloud SQL instance name"
  value       = google_sql_database_instance.leadbot.name
}

output "cloud_sql_private_ip" {
  description = "Cloud SQL private IP"
  value       = google_sql_database_instance.leadbot.private_ip_address
}

output "redis_host" {
  description = "Redis host"
  value       = google_redis_instance.leadbot.host
}

output "redis_port" {
  description = "Redis port"
  value       = google_redis_instance.leadbot.port
}
