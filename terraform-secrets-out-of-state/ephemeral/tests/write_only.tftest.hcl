# The AWS provider is mocked; the random provider runs for real and needs no credentials.
# A write-only argument cannot be asserted on: it is null wherever a test can look. Assert on the version.

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

  assert {
    condition     = aws_secretsmanager_secret_version.db.secret_string_wo == null
    error_message = "A write-only argument should read back as null."
  }
}

run "rejects_a_fractional_version" {
  command = plan

  variables {
    password_version = 1.5
  }

  expect_failures = [var.password_version]
}
