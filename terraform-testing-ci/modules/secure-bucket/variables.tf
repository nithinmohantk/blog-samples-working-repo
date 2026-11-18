variable "name" {
  description = "Short name of the bucket. The environment and account id are appended."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,30}[a-z0-9]$", var.name))
    error_message = "name must be 4 to 32 characters: lower-case letters, digits and hyphens, starting with a letter."
  }
}

variable "environment" {
  description = "Deployment environment."
  type        = string

  validation {
    condition     = contains(["dev", "test", "prod"], var.environment)
    error_message = "environment must be dev, test or prod."
  }
}

variable "data_classification" {
  description = "Classification of the data the bucket will hold."
  type        = string

  validation {
    condition     = contains(["internal", "confidential", "clinical"], var.data_classification)
    error_message = "data_classification must be internal, confidential or clinical."
  }
}

variable "kms_key_arn" {
  description = "ARN of the customer-managed KMS key used for default encryption."
  type        = string

  validation {
    condition     = can(regex("^arn:aws[a-z-]*:kms:[a-z0-9-]+:[0-9]{12}:key/.+$", var.kms_key_arn))
    error_message = "kms_key_arn must be the ARN of a KMS key."
  }
}

variable "noncurrent_retention_days" {
  description = "Days a superseded object version is kept before it expires."
  type        = number
  default     = 365

  validation {
    condition     = var.noncurrent_retention_days >= 30
    error_message = "noncurrent_retention_days must be at least 30."
  }

  validation {
    condition     = var.data_classification != "clinical" || var.noncurrent_retention_days >= 365
    error_message = "Clinical data must keep superseded versions for at least 365 days."
  }
}

variable "force_destroy" {
  description = "Allow the bucket to be destroyed while it still holds objects. Never in production."
  type        = bool
  default     = false

  validation {
    condition     = !(var.force_destroy && var.environment == "prod")
    error_message = "force_destroy cannot be enabled in prod."
  }
}

variable "account_id" {
  description = "AWS account id. When null it is looked up from the caller's credentials."
  type        = string
  default     = null
}
