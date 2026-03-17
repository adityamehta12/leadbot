terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project     = var.project_id
  region      = var.region
  access_token = var.google_access_token != "" ? var.google_access_token : null
}

# ── Enable required APIs ─────────────────────────────────────
locals {
  apis = [
    "run.googleapis.com",
    "sqladmin.googleapis.com",
    "redis.googleapis.com",
    "secretmanager.googleapis.com",
    "artifactregistry.googleapis.com",
    "compute.googleapis.com",
    "vpcaccess.googleapis.com",
    "iam.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "servicenetworking.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each           = toset(local.apis)
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# ── Artifact Registry ────────────────────────────────────────
resource "google_artifact_registry_repository" "leadbot" {
  location      = var.region
  repository_id = "leadbot"
  format        = "DOCKER"
  description   = "LeadBot Docker images"

  depends_on = [google_project_service.apis]
}
