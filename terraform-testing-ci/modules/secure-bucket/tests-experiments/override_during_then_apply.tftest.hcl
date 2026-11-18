# An experiment, expected to fail. With "override_during = plan" on the provider and defaults for only
# some attributes of a resource, an apply run gets one set of generated values for the remaining
# attributes while planning and a different set while applying.
# Run with: terraform test -test-directory=tests-experiments

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

run "apply_after_plan_time_generation" {
  command = apply
}
