locals {
  bucket_name = "${var.project_id}-${var.name_prefix}-bronze"
  sa_member   = "serviceAccount:${google_service_account.pipeline.email}"

  # dbt's bigquery target writes each layer to "<dataset>_<layer>" (see
  # transform/macros/generate_schema_name.sql), so every dataset dbt uses is declared here
  # and the service account never needs permission to create datasets.
  dbt_dataset_base = replace(var.name_prefix, "-", "_")
  dbt_layers       = ["staging", "intermediate", "core", "analytics", "reference"]
}

resource "google_project_service" "apis" {
  for_each = toset(["bigquery.googleapis.com", "storage.googleapis.com", "iam.googleapis.com"])

  service            = each.value
  disable_on_destroy = false
}

# --- Bronze landing zone (the cloud twin of data/bronze/) ------------------------------------

resource "google_storage_bucket" "bronze" {
  name                        = local.bucket_name
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  labels                      = var.labels

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age = var.bronze_nearline_after_days
    }
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
  }

  # Versioning keeps overwritten bronze partitions recoverable for a while; old versions
  # are removed after noncurrent_version_retention_days so they do not pile up forever.
  lifecycle_rule {
    condition {
      days_since_noncurrent_time = var.noncurrent_version_retention_days
      with_state                 = "ARCHIVED"
    }
    action {
      type = "Delete"
    }
  }

  # Bronze is the only copy of history, so deleting live objects is opt-in (default off).
  dynamic "lifecycle_rule" {
    for_each = var.bronze_retention_days == null ? [] : [var.bronze_retention_days]
    content {
      condition {
        age = lifecycle_rule.value
      }
      action {
        type = "Delete"
      }
    }
  }

  depends_on = [google_project_service.apis]
}

# --- Warehouse ------------------------------------------------------------------------------

resource "google_bigquery_dataset" "raw" {
  dataset_id    = replace("${var.name_prefix}_raw", "-", "_")
  friendly_name = "Job market raw"
  description   = "Bronze postings loaded from GCS (bq load / dbt source)."
  location      = var.region
  labels        = var.labels

  depends_on = [google_project_service.apis]
}

# dbt's default dataset (models without a layer) plus one dataset per dbt layer.
resource "google_bigquery_dataset" "dbt" {
  for_each = toset(concat([""], local.dbt_layers))

  dataset_id    = each.value == "" ? local.dbt_dataset_base : "${local.dbt_dataset_base}_${each.value}"
  friendly_name = each.value == "" ? "Job market (dbt default)" : "Job market ${each.value}"
  description   = "dbt models, ${each.value == "" ? "default dataset" : "${each.value} layer"}."
  location      = var.region
  labels        = var.labels

  depends_on = [google_project_service.apis]
}

# Same columns as the local bronze JSONL; partition + cluster mirror the Hive layout.
resource "google_bigquery_table" "bronze_postings" {
  dataset_id          = google_bigquery_dataset.raw.dataset_id
  table_id            = "bronze_postings"
  deletion_protection = true
  labels              = var.labels

  time_partitioning {
    type  = "DAY"
    field = "snapshot_date"
  }

  clustering = ["source", "board"]

  schema = jsonencode([
    { name = "source", type = "STRING", mode = "REQUIRED" },
    { name = "board", type = "STRING", mode = "REQUIRED" },
    { name = "snapshot_date", type = "DATE", mode = "REQUIRED" },
    { name = "company", type = "STRING", mode = "NULLABLE" },
    { name = "extracted_at", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "posting_id", type = "STRING", mode = "REQUIRED" },
    { name = "payload", type = "JSON", mode = "NULLABLE" },
  ])
}

# One row per board extraction attempt, matching bronze/manifests. Successful manifests
# distinguish closures from failed observations in the lifecycle model.
resource "google_bigquery_table" "bronze_manifests" {
  dataset_id          = google_bigquery_dataset.raw.dataset_id
  table_id            = "bronze_manifests"
  deletion_protection = true
  labels              = var.labels

  time_partitioning {
    type  = "DAY"
    field = "snapshot_date"
  }

  clustering = ["source", "board"]

  schema = jsonencode([
    { name = "source", type = "STRING", mode = "REQUIRED" },
    { name = "board", type = "STRING", mode = "REQUIRED" },
    { name = "snapshot_date", type = "DATE", mode = "REQUIRED" },
    { name = "company", type = "STRING", mode = "NULLABLE" },
    { name = "extracted_at", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "status", type = "STRING", mode = "REQUIRED" },
    { name = "fetch_mode", type = "STRING", mode = "REQUIRED" },
    { name = "http_status", type = "INTEGER", mode = "NULLABLE" },
    { name = "attempts", type = "INTEGER", mode = "NULLABLE" },
    { name = "posting_count", type = "INTEGER", mode = "REQUIRED" },
    { name = "reject_count", type = "INTEGER", mode = "REQUIRED" },
    { name = "url", type = "STRING", mode = "NULLABLE" },
    { name = "error", type = "STRING", mode = "NULLABLE" },
    { name = "rejected_posting_ids", type = "STRING", mode = "REPEATED" },
  ])
}

# --- Least-privilege identity for the pipeline -------------------------------------------------
# No key is created here: run as this account via workload identity federation (e.g. GitHub
# OIDC) or `gcloud ... --impersonate-service-account`, never with a downloaded JSON key.

resource "google_service_account" "pipeline" {
  account_id   = "${var.name_prefix}-pipeline"
  display_name = "jobpipe (extract + dbt)"

  depends_on = [google_project_service.apis]
}

resource "google_storage_bucket_iam_member" "pipeline_bronze_writer" {
  bucket = google_storage_bucket.bronze.name
  role   = "roles/storage.objectAdmin"
  member = local.sa_member
}

resource "google_bigquery_dataset_iam_member" "pipeline_raw_editor" {
  dataset_id = google_bigquery_dataset.raw.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = local.sa_member
}

resource "google_bigquery_dataset_iam_member" "pipeline_dbt_editor" {
  for_each = google_bigquery_dataset.dbt

  dataset_id = each.value.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = local.sa_member
}

resource "google_project_iam_member" "pipeline_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = local.sa_member
}
