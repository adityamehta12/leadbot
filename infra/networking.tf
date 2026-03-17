# ── VPC ───────────────────────────────────────────────────────
resource "google_compute_network" "leadbot" {
  name                    = "leadbot-vpc"
  auto_create_subnetworks = false

  depends_on = [google_project_service.apis]
}

resource "google_compute_subnetwork" "leadbot" {
  name          = "leadbot-subnet"
  ip_cidr_range = "10.0.0.0/20"
  region        = var.region
  network       = google_compute_network.leadbot.id
}

# ── Serverless VPC Connector ─────────────────────────────────
resource "google_vpc_access_connector" "leadbot" {
  name          = "leadbot-connector"
  region        = var.region
  ip_cidr_range = "10.8.0.0/28"
  network       = google_compute_network.leadbot.name

  depends_on = [google_project_service.apis]
}

# ── Cloud NAT (outbound internet for VPC) ────────────────────
resource "google_compute_router" "leadbot" {
  name    = "leadbot-router"
  region  = var.region
  network = google_compute_network.leadbot.id
}

resource "google_compute_router_nat" "leadbot" {
  name                               = "leadbot-nat"
  router                             = google_compute_router.leadbot.name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}

# ── Firewall rules ───────────────────────────────────────────
resource "google_compute_firewall" "allow_internal" {
  name    = "leadbot-allow-internal"
  network = google_compute_network.leadbot.name

  allow {
    protocol = "tcp"
  }
  allow {
    protocol = "udp"
  }
  allow {
    protocol = "icmp"
  }

  source_ranges = ["10.0.0.0/20", "10.8.0.0/28"]
}

resource "google_compute_firewall" "deny_external" {
  name     = "leadbot-deny-external"
  network  = google_compute_network.leadbot.name
  priority = 65534

  deny {
    protocol = "all"
  }

  source_ranges = ["0.0.0.0/0"]
}

# ── Private Service Access (for Cloud SQL) ───────────────────
resource "google_compute_global_address" "private_ip" {
  name          = "leadbot-private-ip"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.leadbot.id
}

resource "google_service_networking_connection" "private" {
  network                 = google_compute_network.leadbot.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_ip.name]
}
