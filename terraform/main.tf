provider "google" {
  region      = var.region
  project     = var.project_name
  credentials = file(var.credentials_file_path)
  zone        = var.region_zone
}

# Generate a random vm name
resource "random_string" "seed" {
  length  = 6
  upper   = false
  number  = false
  lower   = true
  special = false
}

locals {
  topic-name = "${random_string.seed.result}-rally-scheduler-topc"
  job-name = "${random_string.seed.result}-rally-scheduler-job"
  bucket-name = "${random_string.seed.result}-rally-on-gcp-deployment"
}

resource "google_pubsub_topic" "topic" {
  name = local.topic-name
}

resource "google_cloud_scheduler_job" "job" {
  name        = local.job-name
  description = "a job to kick off the Rally updater"
  schedule    = "1 */4 * * *"

  pubsub_target {
    topic_name = google_pubsub_topic.topic.id
    data       = base64encode("test")
  }
}

resource "google_storage_bucket" "deployment_bucket" {
  name = local.bucket-name
}

data "archive_file" "src" {
  type        = "zip"
  source_dir  = "${path.root}/../python"
  output_path = "/tmp/function.zip"
}

resource "google_storage_bucket_object" "archive" {
  name   = "${data.archive_file.src.output_md5}.zip"
  bucket = google_storage_bucket.deployment_bucket.name
  source = "/tmp/function.zip"
}

resource "google_cloudfunctions_function" "scheduler_function" {
  name        = "rally-scheduler-function"
  description = "A Cloud Function that is triggered by a Cloud Schedule."
  runtime     = "python37"

  environment_variables = {
    APIKEY = var.rally_api_key
    RALLY_WORKSPACE = var.rally_workspace
    RALLY_PROJECT = var.rally_project
    RALLY_SCAN_OFFSET = var.rally_scan_offset
  }

  available_memory_mb   = 128
  source_archive_bucket = google_storage_bucket.deployment_bucket.name
  source_archive_object = google_storage_bucket_object.archive.name
  timeout               = 500
  entry_point           = "scheduler"

  event_trigger {
    event_type = "google.pubsub.topic.publish"
    resource = google_pubsub_topic.topic.name
  }
}

resource "google_bigquery_dataset" "rally" {
  dataset_id                  = "rally"
  friendly_name               = "rally"
  description                 = "Dataset for Rally statistics"
}

resource "google_bigquery_table" "schedule_events" {
  dataset_id = google_bigquery_dataset.rally.dataset_id
  table_id   = "schedule_events"
  schema = <<EOF
[
  {
    "name": "rally_id",
    "type": "STRING",
    "mode": "REQUIRED",
    "description": "Rally Object's Formatted ID"
  },
  {
    "name": "schedule_state_id",
    "type": "INTEGER",
    "mode": "REQUIRED",
    "description": "Scheduled State"
  },
  {
    "name": "schedule_state_name",
    "type": "STRING",
    "mode": "REQUIRED",
    "description": "Scheduled State"
  },
  {
    "name": "event_type_id",
    "type": "INTEGER",
    "mode": "REQUIRED",
    "description": "ARRIVAL or DEPARTURE"
  },
  {
    "name": "event_type_name",
    "type": "STRING",
    "mode": "REQUIRED",
    "description": "ARRIVAL or DEPARTURE"
  },
  {
    "name": "timestamp",
    "type": "TIMESTAMP",
    "mode": "REQUIRED",
    "description": "Event's Timestamp"
  },
  {
    "name": "path_to_root",
    "type": "STRING",
    "mode": "REQUIRED",
    "description": "Path to the Root Project"
  },
  {
    "name": "blocked_state",
    "type": "STRING",
    "mode": "NULLABLE",
    "description": "Blocked State (On|Off|Null)"
  },
  {
    "name": "ready_state",
    "type": "STRING",
    "mode": "NULLABLE",
    "description": "Ready State (On|Off|Null|"
  }
]
EOF
}

