variable "project_id" {
  description = "GCP project that would host the pipeline (never applied from this repo)."
  type        = string
}

variable "region" {
  description = "Location for the bucket and BigQuery datasets."
  type        = string
  default     = "northamerica-northeast1"
}

variable "name_prefix" {
  description = "Prefix for resource names."
  type        = string
  default     = "job-market"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,20}$", var.name_prefix))
    error_message = "name_prefix must be 3-21 chars of lowercase letters, digits and hyphens."
  }
}

variable "bronze_nearline_after_days" {
  description = "Move bronze objects to NEARLINE storage after this many days."
  type        = number
  default     = 30
}

variable "bronze_retention_days" {
  description = "Delete live bronze objects after this many days. Null (default) keeps bronze forever: it is the only copy of history, and a --full-refresh rebuilds every spell from all of it."
  type        = number
  default     = null

  validation {
    condition     = coalesce(var.bronze_retention_days, 365) >= 365
    error_message = "If set, bronze_retention_days must be at least 365. Deleting bronze truncates the history a full refresh rebuilds from and changes left-censoring, so keep it unless storage cost forces the trade-off."
  }
}

variable "noncurrent_version_retention_days" {
  description = "Delete overwritten (noncurrent) bronze object versions after this many days."
  type        = number
  default     = 30

  validation {
    condition     = var.noncurrent_version_retention_days >= 1
    error_message = "noncurrent_version_retention_days must be at least 1."
  }
}

variable "labels" {
  description = "Labels applied to every labelled resource."
  type        = map(string)
  default = {
    app        = "jobpipe"
    managed_by = "terraform"
  }
}
