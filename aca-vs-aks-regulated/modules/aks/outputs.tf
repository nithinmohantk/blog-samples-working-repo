# The same control names are reported by the Container Apps module, so one test can ask both the same questions.
output "controls" {
  description = "Whether each control in the baseline is configured."
  value = {
    no_public_endpoint         = azurerm_kubernetes_cluster.this.private_cluster_enabled && !azurerm_kubernetes_cluster.this.private_cluster_public_fqdn_enabled
    zone_redundant             = length(azurerm_kubernetes_cluster.this.default_node_pool[0].zones) == 3 && length(azurerm_kubernetes_cluster_node_pool.workload.zones) == 3
    workload_identity          = azurerm_kubernetes_cluster.this.oidc_issuer_enabled && azurerm_kubernetes_cluster.this.workload_identity_enabled
    no_registry_password       = azurerm_kubernetes_cluster.this.local_account_disabled
    encrypted_between_services = false
    logs_to_workspace          = azurerm_kubernetes_cluster.this.oms_agent[0].log_analytics_workspace_id == var.log_analytics_workspace_id
    at_least_three_replicas    = azurerm_kubernetes_cluster_node_pool.workload.min_count >= 3
  }
}

output "platform_id" {
  description = "Resource id of the cluster."
  value       = azurerm_kubernetes_cluster.this.id
}
