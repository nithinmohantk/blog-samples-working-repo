terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.63.0"
    }
  }
}

# Enough for "plan" to run with no AWS account: nothing here is ever applied.
provider "aws" {
  region                      = "eu-west-1"
  access_key                  = "plan-only"
  secret_key                  = "plan-only"
  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
  skip_region_validation      = true
}

module "discharge_summaries" {
  source = "../../modules/secure-bucket"

  name                = "discharge-summaries"
  environment         = "prod"
  data_classification = "clinical"
  kms_key_arn         = "arn:aws:kms:eu-west-1:111122223333:key/11111111-2222-3333-4444-555555555555"
  account_id          = "111122223333"
}
