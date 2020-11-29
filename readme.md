# Export Rally Data to BQ for Analysis

## Introduction

We created this project as an evolution of the previous attempt
that worked by extracting data from Rally, then generating a fixed number of reports
and graphs. This project simply extracts data from Rally and
puts it in BigQuery. One can perform the required analysis using 
BigQuery's capability or advanced analytical tools that integrate with BigQuery.

A scheduler runs periodically to keep the data in 
BigQuery up to date.

As of the time of writing (11/29/2020), it is still WIP.

## Getting Started

Pre-requisites:
* Obtain an API key as described here: https://help.rallydev.com/rally-application-manager
* Install and configure GCP client, including a service account's JSON key file
* Install Terraform (currently, ```v0.12.28```)
* Install (if not already installed) Python 3.7 or later

Each of the directories has a ```readme.md``` with further instructions:
* ```terraform/``` - start by deploying required artifacts to GCP
* ```python/``` - continue with extracting Rally data and loading it into BigQuery
* ```bq/``` - play with the loaded data using BigQuery