# ── Cloud SQL: PostgreSQL 15 ──────────────────────────────────
resource "google_sql_database_instance" "leadbot" {
  name             = "leadbot-db-${var.environment}"
  database_version = "POSTGRES_15"
  region           = var.region

  settings {
    tier      = var.db_tier
    disk_size = var.db_disk_size
    disk_type = "PD_SSD"

    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.leadbot.id
    }

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = var.environment == "prod"
      backup_retention_settings {
        retained_backups = var.environment == "prod" ? 30 : 7
      }
    }
  }

  deletion_protection = var.environment == "prod"

  depends_on = [google_service_networking_connection.private]
}

resource "google_sql_database" "leadbot" {
  name     = "leadbot"
  instance = google_sql_database_instance.leadbot.name
}

resource "google_sql_user" "leadbot" {
  name     = "leadbot"
  instance = google_sql_database_instance.leadbot.name
  password = "leadbot" # Override via Secret Manager in prod
}
