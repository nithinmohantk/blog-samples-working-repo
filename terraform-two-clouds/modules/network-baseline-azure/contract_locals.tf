# Shared derivations. This file is identical in every implementation; CI fails if the copies drift.

locals {
  prefix = "${var.name}-${var.environment}"

  # Two bits of subnetting: up to four equal subnets, named the same way on every cloud.
  subnets = {
    for index in range(var.subnet_count) :
    format("private-%d", index + 1) => cidrsubnet(var.address_space, 2, index)
  }

  tags = merge(var.tags, {
    workload    = var.name
    environment = var.environment
    managed-by  = "terraform"
  })
}
