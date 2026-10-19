terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.0, < 8.0"
    }
  }
}

variable "project_id" { type = string }
variable "source_dataset" { type = string }
variable "region" { type = string }
variable "spanner_instance" { type = string }
variable "spanner_database" { type = string }
variable "workflow_name" { type = string }
variable "schedule" { type = string }
variable "schedule_paused" { type = bool }
variable "time_zone" { type = string }

provider "google" {
  project = var.project_id
  region  = var.region
}

resource "google_project_service" "apis" {
  for_each = toset([
    "bigquery.googleapis.com", "spanner.googleapis.com", "workflows.googleapis.com",
    "workflowexecutions.googleapis.com", "cloudscheduler.googleapis.com",
    "logging.googleapis.com", "monitoring.googleapis.com", "iam.googleapis.com"
  ])
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_service_account" "runtime" {
  project      = var.project_id
  account_id   = "graphkit-bq-spanner"
  display_name = "Customers_data native reverse ETL runtime"
  depends_on   = [google_project_service.apis]
}

resource "google_service_account" "trigger" {
  project      = var.project_id
  account_id   = "graphkit-sync-trigger"
  display_name = "Customers_data workflow scheduler"
  depends_on   = [google_project_service.apis]
}

resource "google_spanner_database" "serving" {
  project             = var.project_id
  instance            = var.spanner_instance
  name                = var.spanner_database
  database_dialect    = "GOOGLE_STANDARD_SQL"
  ddl                 = jsondecode(file("${path.module}/generated/schema.json"))
  deletion_protection = true
  depends_on          = [google_project_service.apis]
  lifecycle { prevent_destroy = true }
}

resource "google_bigquery_dataset_iam_member" "source_read" {
  project    = var.project_id
  dataset_id = var.source_dataset
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_project_iam_member" "submit_jobs" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_spanner_instance_iam_member" "view_instance" {
  project  = var.project_id
  instance = var.spanner_instance
  role     = "roles/spanner.viewer"
  member   = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_spanner_database_iam_member" "target_write" {
  project  = var.project_id
  instance = var.spanner_instance
  database = google_spanner_database.serving.name
  role     = "roles/spanner.databaseUser"
  member   = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_project_iam_member" "logs" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_workflows_workflow" "pipeline" {
  project         = var.project_id
  region          = var.region
  name            = var.workflow_name
  description     = "Native BigQuery EXPORT DATA from Customers_data to Spanner; snapshot upserts, validated keys, fail-closed lock."
  service_account = google_service_account.runtime.email
  source_contents = file("${path.module}/generated/workflow.json")
  call_log_level  = "LOG_ERRORS_ONLY"
  labels          = { purpose = "customers-reverse-etl", managed_by = "graphkit" }
  depends_on = [
    google_project_service.apis, google_bigquery_dataset_iam_member.source_read,
    google_project_iam_member.submit_jobs, google_spanner_instance_iam_member.view_instance,
    google_spanner_database_iam_member.target_write, google_project_iam_member.logs
  ]
}

resource "google_project_iam_member" "invoke" {
  project = var.project_id
  role    = "roles/workflows.invoker"
  member  = "serviceAccount:${google_service_account.trigger.email}"
}

resource "google_cloud_scheduler_job" "refresh" {
  project          = var.project_id
  region           = var.region
  name             = "customers-to-spanner-refresh"
  description      = "Trigger the Customers_data upsert workflow every hour."
  schedule         = var.schedule
  time_zone        = var.time_zone
  paused           = var.schedule_paused
  attempt_deadline = "30s"
  retry_config { retry_count = 0 }
  http_target {
    http_method = "POST"
    uri         = "https://workflowexecutions.googleapis.com/v1/${google_workflows_workflow.pipeline.id}/executions"
    headers     = { "Content-Type" = "application/json" }
    body        = base64encode("{}")
    oauth_token {
      service_account_email = google_service_account.trigger.email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }
  depends_on = [google_project_iam_member.invoke]
}

resource "google_logging_metric" "errors" {
  project = var.project_id
  name    = "graphkit_customers_pipeline_errors"
  filter  = "resource.type=\"workflows.googleapis.com/Workflow\" AND resource.labels.workflow_id=\"${var.workflow_name}\" AND severity>=ERROR"
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
  }
  depends_on = [google_project_service.apis]
}

resource "google_monitoring_alert_policy" "errors" {
  project      = var.project_id
  display_name = "Customers_data to Spanner workflow failures"
  combiner     = "OR"
  conditions {
    display_name = "Workflow error logged"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.errors.name}\" AND resource.type=\"workflows.googleapis.com/Workflow\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_DELTA"
      }
    }
  }
  documentation {
    content   = "Inspect the Workflows execution and its deterministic gk-EXECUTION_ID-* BigQuery jobs. Failures retain the Spanner GraphkitPipelineLock. Clear a stale lock only after verifying that the owning execution and export jobs have stopped."
    mime_type = "text/markdown"
  }
  depends_on = [google_project_service.apis]
}

output "workflow" { value = google_workflows_workflow.pipeline.id }
output "spanner_database" { value = google_spanner_database.serving.id }
output "scheduler_paused" { value = google_cloud_scheduler_job.refresh.paused }
