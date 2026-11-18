# Terraform only. "override_during = plan" makes a mocked provider produce computed values while
# planning, so a plan run can assert on them. OpenTofu 1.12 does not accept the argument.
# Run with: terraform test -test-directory=tests-terraform-only

mock_provider "aws" {
  override_during = plan

  mock_resource "aws_s3_bucket" {
    defaults = {
      arn = "arn:aws:s3:::mocked-bucket"
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

run "policy_is_checked_without_an_apply" {
  command = plan

  assert {
    condition     = contains(jsondecode(aws_s3_bucket_policy.this.policy).Statement[0].Resource, "arn:aws:s3:::mocked-bucket/*")
    error_message = "The policy must cover the objects in the bucket."
  }
}
