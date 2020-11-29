# Deploy to GCP

We tested it with a free-tier GCP account. 

## How to run

Read the pre-requisites in the main ```readme.md```. 
In short, you will need to have a GCP account with a corresponding JSON key file,
Terraform and Rally API key. 
 
```bash
terraform apply \
    -var='region=us-central1' \
    -var='region_zone=us-central1-a' \
    -var='project_name=my-project-id' \
    -var='credentials_file_path=~/.gcloud/Terraform.json' \
    -var='rally_api_key=your-rally-api-key' \
    -var='rally_workspace=your-rally-workspace' \
    -var='rally_project=your-root-rally-project' \
    -var='rally_scan_offset=1' \
```

## TODO

* Figure out how to enable APIs (GCP complains about for four or five)
* Apply Terraform best practices