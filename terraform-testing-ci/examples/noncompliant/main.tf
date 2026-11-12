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

# What the policy gate exists to stop: a bucket for clinical data written by hand, outside the module.
resource "aws_s3_bucket" "scratch" {
  bucket        = "scratch-exports-prod-111122223333"
  force_destroy = true

  tags = {
    environment         = "prod"
    data-classification = "clinical"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "scratch" {
  bucket = aws_s3_bucket.scratch.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "scratch" {
  bucket = aws_s3_bucket.scratch.id

  block_public_acls       = true
  block_public_policy     = false
  ignore_public_acls      = true
  restrict_public_buckets = false
}
