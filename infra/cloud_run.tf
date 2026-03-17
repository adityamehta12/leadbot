# ── Cloud Run: LeadBot API ────────────────────────────────────
resource "google_cloud_run_v2_service" "leadbot_api" {
  name     = "leadbot-api"
  location = var.region

  template {
    scaling {
      min_instance_count = var.cloud_run_min_instances
      max_instance_count = var.cloud_run_max_instances
    }

    service_account = google_service_account.leadbot_api.email

    vpc_access {
      connector = google_vpc_access_connector.leadbot.id
      egress    = "ALL_TRAFFIC"
    }

    timeout = "300s"

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/leadbot/leadbot-api:latest"

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = var.cloud_run_cpu
          memory = var.cloud_run_memory
        }
      }

      startup_probe {
        http_get {
          path = "/api/health"
        }
        initial_delay_seconds = 5
        period_seconds        = 10
        failure_threshold     = 3
      }

      liveness_probe {
        http_get {
          path = "/api/health"
        }
        period_seconds = 30
      }

      env {
        name = "ANTHROPIC_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.anthropic_api_key.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.database_url.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "REDIS_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.redis_url.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "WEBHOOK_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.webhook_url.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "JWT_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.jwt_secret.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "SENDGRID_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.sendgrid_api_key.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "TWILIO_ACCOUNT_SID"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.twilio_account_sid.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "TWILIO_AUTH_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.twilio_auth_token.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "TWILIO_FROM_NUMBER"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.twilio_from_number.secret_id
            version = "latest"
          }
        }
      }
    }
  }

  depends_on = [google_project_service.apis]
}

# ── Public access (allUsers invoker) ─────────────────────────
resource "google_cloud_run_v2_service_iam_member" "public" {
  name     = google_cloud_run_v2_service.leadbot_api.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}
