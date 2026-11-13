# The same outcome with nothing secret in state or plan. The password exists only while the run is in
# progress, and reaches the secret store through a write-only argument.

variable "name" {
  description = "Name of the secret."
  type        = string
}

variable "password_version" {
  description = "Increase by one to generate and store a new password. Nothing else triggers a rotation."
  type        = number
  default     = 1

  validation {
    condition     = var.password_version >= 1 && floor(var.password_version) == var.password_version
    error_message = "password_version must be a whole number, starting at 1."
  }
}

# Not a resource: it has no address in state. A new value is generated on every run that opens it.
ephemeral "random_password" "db" {
  length           = 32
  special          = true
  override_special = "!#%*-_=+"
}

resource "aws_secretsmanager_secret" "db" {
  name                    = var.name
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "db" {
  secret_id = aws_secretsmanager_secret.db.id

  # Sent to the provider, never stored. The version number is what Terraform tracks and diffs.
  secret_string_wo         = ephemeral.random_password.db.result
  secret_string_wo_version = var.password_version
}

output "secret_arn" {
  description = "Consumers read the password from the secret store by this ARN. Terraform cannot give it to them."
  value       = aws_secretsmanager_secret.db.arn
}
