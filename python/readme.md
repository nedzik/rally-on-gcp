# Loader and Cloud Function Handlers

## Pre-requisites

* Create a GCP deployment using Terraform - see ```../terraform/readme.md```
* It is a good idea to create a Python virtual environment
* Install the dependencies: 
```bash
pip install -r requirements.txt
```
* Set the following environment variables:
```bash
export APIKEY=<value>
export RALLY_PROJECT='<value>'
export RALLY_WORKSPACE='<value>'
export GOOGLE_APPLICATION_CREDENTIALS=~/.gcloud/your-key.json 
export RALLY_SCAN_OFFSET=1
```

## How to run the loader

* Ensure the pre-requisites
* Run the loader (replace ```2020-11-01``` with your "from" date):
```bash
    python main.py loader 2020-11-01
```
* The loader will show the progress - currently loading the data
  from 07/01/2020 till 11/29/2020 for a ~150 strong org takes about 
  30 minutes due to how Rally navigates its object graph.
  
## Testing Cloud Function Handler for Scheduler

It is still WIP, only printing the Rally items that have changed
within the scan window. One can run it outside of GCP by following these steps:

* Ensure the pre-requisites
* Set ```RALLY_SCAN_OFFSET``` to a different number of days if desired
* Run the scheduler handler:
```bash
python main.py scheduler
```

## Testing Cloud Function Handler for Updater

It is still WIP; we still do not even deploy the cloud function.
The handler only prints out the events for the Rally item provided as a parameter. 
One can run it outside of GCP by following these steps:

* Ensure the pre-requisites
* Set ```RALLY_SCAN_OFFSET``` to a different number of days if desired
* Run the scheduler handler:
```bash
python main.py updater <rally-formatted-id>
```

## TODO

* Add a separate table for flow events
* Filter out older Rally items that get in because the re-org recently touched them (e.g. US212917)