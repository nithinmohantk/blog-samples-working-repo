# An experiment, expected to fail. With "override_during = plan" on the whole provider, an apply run
# is given one set of generated values while planning and a different set while applying.
# Run with: terraform test -test-directory=tests-experiments

mock_provider "aws" {
  override_during = plan
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
