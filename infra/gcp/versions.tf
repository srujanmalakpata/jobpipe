terraform {
  required_version = ">= 1.6"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  # Remote state is deliberately not configured: this module is validated in CI with
  # `terraform init -backend=false` and has never been applied. Add a "gcs" backend
  # before using it for real.
}

provider "google" {
  project = var.project_id
  region  = var.region
}
