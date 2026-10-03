output "bronze_bucket" {
  description = "gs:// bucket for bronze JSONL (mirror of data/bronze/)."
  value       = "gs://${google_storage_bucket.bronze.name}"
}

output "raw_dataset" {
  value = google_bigquery_dataset.raw.dataset_id
}

output "dbt_datasets" {
  description = "Datasets dbt writes to. The un-suffixed one is the `dataset` of the bigquery target in transform/profiles.yml; dbt appends _<layer> for each model layer."
  value       = sort([for d in google_bigquery_dataset.dbt : d.dataset_id])
}

output "pipeline_service_account" {
  value = google_service_account.pipeline.email
}
