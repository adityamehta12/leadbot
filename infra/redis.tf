# ── Redis: Memorystore ────────────────────────────────────────
resource "google_redis_instance" "leadbot" {
  name           = "leadbot-redis-${var.environment}"
  tier           = "BASIC"
  memory_size_gb = var.redis_memory_size_gb
  region         = var.region

  authorized_network = google_compute_network.leadbot.id

  redis_version = "REDIS_7_0"

  depends_on = [google_project_service.apis]
}
