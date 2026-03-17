# ── LeadBot API service account ──────────────────────────────
resource "google_service_account" "leadbot_api" {
  account_id   = "leadbot-api-sa"
  display_name = "LeadBot API Service Account"
}

resource "google_project_iam_member" "leadbot_api_roles" {
  for_each = toset([
    "roles/cloudsql.client",
    "roles/secretmanager.secretAccessor",
    "roles/logging.logWriter",
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.leadbot_api.email}"
}

# ── CI/CD service account ────────────────────────────────────
resource "google_service_account" "leadbot_cicd" {
  account_id   = "leadbot-cicd-sa"
  display_name = "LeadBot CI/CD Service Account"
}

resource "google_project_iam_member" "leadbot_cicd_roles" {
  for_each = toset([
    "roles/artifactregistry.writer",
    "roles/run.admin",
    "roles/iam.serviceAccountUser",
    "roles/secretmanager.secretAccessor",
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.leadbot_cicd.email}"
}
