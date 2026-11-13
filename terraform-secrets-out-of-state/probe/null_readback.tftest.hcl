# Not part of the module's tests. Copied in by run_experiments.py to record how each tool presents a
# write-only argument to a test that runs against a mocked provider.

mock_provider "aws" {}

variables {
  name = "sample/db-password"
}

run "write_only_value_reads_as_null" {
  command = plan

  assert {
    condition     = aws_secretsmanager_secret_version.db.secret_string_wo == null
    error_message = "The write-only argument did not read back as null."
  }
}
