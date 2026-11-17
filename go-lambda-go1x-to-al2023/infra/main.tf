# The function after the move: provided.al2023 on arm64, with a published version behind an alias so the
# switch can be rolled back by moving the alias, not by redeploying go1.x (which Lambda stops accepting).
terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "5.31.0"
    }
  }
}

variable "package_path" {
  description = "Zip containing a single executable named bootstrap, built with -tags lambda.norpc."
  type        = string
}

variable "execution_role_arn" {
  type = string
}

resource "aws_lambda_function" "order_status" {
  function_name    = "order-status"
  role             = var.execution_role_arn
  filename         = var.package_path
  source_code_hash = filebase64sha256(var.package_path)

  runtime       = "provided.al2023"
  handler       = "bootstrap" # ignored by the OS-only runtime, but required by the API
  architectures = ["arm64"]
  memory_size   = 256
  timeout       = 10
  publish       = true

  environment {
    variables = {
      # Not needed by Lambda; makes the build mode visible in the console during the migration.
      BUILD_FLAVOUR = "norpc-al2023"
    }
  }
}

resource "aws_lambda_alias" "live" {
  name             = "live"
  function_name    = aws_lambda_function.order_status.function_name
  function_version = aws_lambda_function.order_status.version
}

output "live_alias_arn" {
  value = aws_lambda_alias.live.arn
}
