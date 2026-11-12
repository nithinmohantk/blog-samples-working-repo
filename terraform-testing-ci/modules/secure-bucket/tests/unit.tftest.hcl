# Unit tests. No AWS account, no credentials, no calls to AWS: the provider is mocked.
# The file runs unchanged under "terraform test" and "tofu test".
#
# Rule used throughout: assert on values the configuration sets in "plan" runs, and on values
# the provider computes (ARNs, ids, anything read from a data source) in "apply" runs.
# An apply against a mocked provider creates nothing and costs nothing.

mock_provider "aws" {
  mock_resource "aws_s3_bucket" {
    defaults = {
      arn = "arn:aws:s3:::mocked-bucket"
    }
  }

  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "444455556666"
    }
  }
}

variables {
  name                = "clinical-docs"
  environment         = "dev"
  data_classification = "clinical"
  kms_key_arn         = "arn:aws:kms:eu-west-1:111122223333:key/11111111-2222-3333-4444-555555555555"
  account_id          = "111122223333"
}

run "name_carries_environment_and_account" {
  command = plan

  assert {
    condition     = aws_s3_bucket.this.bucket == "clinical-docs-dev-111122223333"
    error_message = "The bucket name must be <name>-<environment>-<account id>."
  }

  assert {
    condition     = aws_s3_bucket.this.tags["data-classification"] == "clinical"
    error_message = "The bucket must carry its data classification as a tag."
  }
}

run "explicit_account_id_skips_the_lookup" {
  command = plan

  assert {
    condition     = length(data.aws_caller_identity.current) == 0
    error_message = "No caller identity lookup should happen when account_id is given."
  }
}

run "account_id_is_looked_up_when_not_given" {
  command = apply

  variables {
    account_id = null
  }

  assert {
    condition     = length(data.aws_caller_identity.current) == 1
    error_message = "The caller identity must be looked up when account_id is null."
  }

  assert {
    condition     = aws_s3_bucket.this.bucket == "clinical-docs-dev-444455556666"
    error_message = "The looked-up account id must be used in the name."
  }
}

run "default_encryption_uses_the_customer_key" {
  command = plan

  assert {
    condition     = one(aws_s3_bucket_server_side_encryption_configuration.this.rule).apply_server_side_encryption_by_default[0].sse_algorithm == "aws:kms"
    error_message = "Default encryption must be SSE-KMS."
  }

  assert {
    condition     = one(aws_s3_bucket_server_side_encryption_configuration.this.rule).apply_server_side_encryption_by_default[0].kms_master_key_id == var.kms_key_arn
    error_message = "Default encryption must use the key that was passed in."
  }
}

run "public_access_is_blocked_four_ways" {
  command = plan

  assert {
    condition = alltrue([
      aws_s3_bucket_public_access_block.this.block_public_acls,
      aws_s3_bucket_public_access_block.this.block_public_policy,
      aws_s3_bucket_public_access_block.this.ignore_public_acls,
      aws_s3_bucket_public_access_block.this.restrict_public_buckets,
    ])
    error_message = "All four public access block settings must be true."
  }
}

run "versioning_is_on" {
  command = plan

  assert {
    condition     = aws_s3_bucket_versioning.this.versioning_configuration[0].status == "Enabled"
    error_message = "Versioning must be enabled."
  }
}

run "policy_denies_plain_http" {
  # The policy embeds the bucket ARN, which the provider computes: an apply run.
  command = apply

  assert {
    condition     = jsondecode(aws_s3_bucket_policy.this.policy).Statement[0].Effect == "Deny"
    error_message = "The transport statement must be a Deny."
  }

  assert {
    condition     = jsondecode(aws_s3_bucket_policy.this.policy).Statement[0].Condition.Bool["aws:SecureTransport"] == "false"
    error_message = "The policy must deny requests that are not made over TLS."
  }

  assert {
    condition     = contains(jsondecode(aws_s3_bucket_policy.this.policy).Statement[0].Resource, "arn:aws:s3:::mocked-bucket/*")
    error_message = "The policy must cover the objects in the bucket."
  }
}

run "superseded_versions_are_kept_for_a_year_by_default" {
  command = plan

  assert {
    condition     = aws_s3_bucket_lifecycle_configuration.this.rule[0].noncurrent_version_expiration[0].noncurrent_days == 365
    error_message = "The default retention for superseded versions must be 365 days."
  }
}

run "rejects_a_malformed_name" {
  command = plan

  variables {
    name = "Clinical_Docs"
  }

  expect_failures = [var.name]
}

run "rejects_force_destroy_in_prod" {
  command = plan

  variables {
    environment   = "prod"
    force_destroy = true
  }

  expect_failures = [var.force_destroy]
}

run "rejects_short_retention_for_clinical_data" {
  command = plan

  variables {
    noncurrent_retention_days = 90
  }

  expect_failures = [var.noncurrent_retention_days]
}

run "allows_short_retention_for_internal_data" {
  command = plan

  variables {
    data_classification       = "internal"
    noncurrent_retention_days = 90
  }

  assert {
    condition     = aws_s3_bucket_lifecycle_configuration.this.rule[0].noncurrent_version_expiration[0].noncurrent_days == 90
    error_message = "Internal data may use a shorter retention."
  }
}

run "rejects_a_key_that_is_not_a_kms_arn" {
  command = plan

  variables {
    kms_key_arn = "alias/my-key"
  }

  expect_failures = [var.kms_key_arn]
}

run "apply_with_mocks_exposes_outputs" {
  command = apply

  assert {
    condition     = output.bucket_arn == "arn:aws:s3:::mocked-bucket"
    error_message = "bucket_arn must be the ARN of the bucket resource."
  }

  assert {
    condition     = output.bucket_name == "clinical-docs-dev-111122223333"
    error_message = "bucket_name must be the name of the bucket resource."
  }
}
