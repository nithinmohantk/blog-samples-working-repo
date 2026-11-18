# The pattern this article argues against for anything but small estates: one module with a switch.
# It is here so its costs can be measured beside the two-module design.

variable "cloud" {
  description = "Which cloud to build the baseline in."
  type        = string

  validation {
    condition     = contains(["aws", "azure"], var.cloud)
    error_message = "cloud must be aws or azure."
  }
}

variable "name" { type = string }
variable "environment" { type = string }
variable "region" { type = string }
variable "address_space" { type = string }

module "aws" {
  source = "../network-baseline-aws"
  count  = var.cloud == "aws" ? 1 : 0

  name          = var.name
  environment   = var.environment
  region        = var.region
  address_space = var.address_space
}

module "azure" {
  source = "../network-baseline-azure"
  count  = var.cloud == "azure" ? 1 : 0

  name          = var.name
  environment   = var.environment
  region        = var.region
  address_space = var.address_space
}

output "network_id" {
  value = one(concat(module.aws[*].network_id, module.azure[*].network_id))
}

output "subnet_cidrs" {
  value = one(concat(module.aws[*].subnet_cidrs, module.azure[*].subnet_cidrs))
}
