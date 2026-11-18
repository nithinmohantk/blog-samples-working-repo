# The contract. This file is identical in every implementation; CI fails if the copies drift.

output "network_id" {
  description = "Identifier of the virtual network, in the cloud's own format."
  value       = local.network_id
}

output "subnet_ids" {
  description = "Subnet identifiers by subnet name."
  value       = local.subnet_ids
}

output "subnet_cidrs" {
  description = "Subnet CIDR blocks by subnet name."
  value       = local.subnets
}

output "log_store_id" {
  description = "Identifier of the store that receives network logs."
  value       = local.log_store_id
}

output "tags" {
  description = "The tags applied to every resource."
  value       = local.tags
}
