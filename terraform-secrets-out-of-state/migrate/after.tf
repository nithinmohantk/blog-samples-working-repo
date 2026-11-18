# Replaces classic/main.tf in place, to see what moving an existing secret to a write-only argument leaves behind.

variable "name" {
  description = "Name of the secret."
  type        = string
}

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
  secret_id                = aws_secretsmanager_secret.db.id
  secret_string_wo         = ephemeral.random_password.db.result
  secret_string_wo_version = 1
}

output "secret_arn" {
  value = aws_secretsmanager_secret.db.arn
}
