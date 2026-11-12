# The contract. This file is identical in every implementation; CI fails if the copies drift.

variable "name" {
  description = "Short workload name, used in resource names."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9]{2,11}$", var.name))
    error_message = "name must be 3 to 12 lower-case letters and digits, starting with a letter."
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

variable "region" {
  description = "Region, in the cloud's own naming. This is deliberately not abstracted."
  type        = string
}

variable "address_space" {
  description = "IPv4 CIDR block of the network, between /16 and /24."
  type        = string

  validation {
    condition     = can(cidrhost(var.address_space, 0)) && try(tonumber(split("/", var.address_space)[1]) >= 16 && tonumber(split("/", var.address_space)[1]) <= 24, false)
    error_message = "address_space must be an IPv4 CIDR block between /16 and /24."
  }
}

variable "subnet_count" {
  description = "Number of private subnets."
  type        = number
  default     = 2

  validation {
    condition     = var.subnet_count >= 1 && var.subnet_count <= 4 && floor(var.subnet_count) == var.subnet_count
    error_message = "subnet_count must be a whole number from 1 to 4."
  }
}

variable "log_retention_days" {
  description = "Days that network logs are kept."
  type        = number
  default     = 365

  validation {
    condition     = var.log_retention_days >= 90
    error_message = "log_retention_days must be at least 90."
  }
}

variable "tags" {
  description = "Extra tags for every resource."
  type        = map(string)
  default     = {}
}
