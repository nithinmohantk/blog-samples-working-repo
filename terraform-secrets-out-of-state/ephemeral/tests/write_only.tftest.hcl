# The AWS provider is mocked; the random provider runs for real and needs no credentials.
# A test cannot usefully assert on the write-only value itself, so it asserts on the version that travels with it.

mock_provider "aws" {}

variables {
  name = "sample/db-password"
}

run "version_is_tracked_and_value_is_not" {
  command = plan

  assert {
    condition     = aws_secretsmanager_secret_version.db.secret_string_wo_version == 1
    error_message = "The version argument should carry the default of 1."
  }
}

run "rejects_a_fractional_version" {
  command = plan

  variables {
    password_version = 1.5
  }

  expect_failures = [var.password_version]
}
