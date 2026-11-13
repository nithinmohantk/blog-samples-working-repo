# A secret that already exists outside Terraform, such as a token issued by a third party, passed in by the
# pipeline. Marking the variable ephemeral keeps it out of state and plan; it can then only flow to places
# that do not persist it.

variable "name" {
  description = "Name of the secret."
  type        = string
}

variable "api_token" {
  description = "Supplied by the pipeline as TF_VAR_api_token on every run."
  type        = string
  ephemeral   = true
  sensitive   = true
}

variable "api_token_version" {
  description = "Increase by one when the token has been reissued."
  type        = number
  default     = 1
}

resource "aws_secretsmanager_secret" "token" {
  name                    = var.name
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "token" {
  secret_id                = aws_secretsmanager_secret.token.id
  secret_string_wo         = var.api_token
  secret_string_wo_version = var.api_token_version
}
