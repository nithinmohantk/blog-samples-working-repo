# The long-standing pattern: generate a password as a managed resource and hand it to the secret store.
# It works, and it writes the password into the state file twice.

variable "name" {
  description = "Name of the secret."
  type        = string
}

resource "random_password" "db" {
  length           = 32
  special          = true
  override_special = "!#%*-_=+"
}

resource "aws_secretsmanager_secret" "db" {
  name                    = var.name
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "db" {
  secret_id     = aws_secretsmanager_secret.db.id
  secret_string = random_password.db.result
}

output "secret_arn" {
  value = aws_secretsmanager_secret.db.arn
}
