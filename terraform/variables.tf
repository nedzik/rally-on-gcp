variable "region" {
  default = "us-central1"
}

variable "region_zone" {
  default = "us-central1-a"
}

variable "project_name" {
  description = "The ID of the Google Cloud project"
}

variable "credentials_file_path" {
  description = "Path to the JSON file used to describe your account credentials"
}

variable "rally_api_key" {
  description = "Rally API key"
}

variable "rally_workspace" {
  description = "Rally Workspace"
}

variable "rally_project" {
  description = "The project in Rally workspace that you want to use as the root for your data collection"
}

variable "rally_scan_offset" {
  description = "Offset (in days) that scheduler will use to scan for updated stories/defects"
  default = "1"
}
