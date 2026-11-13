# The same control names are reported by the AKS module, so one test can ask both the same questions.
output "controls" {
  description = "Whether each control in the baseline is configured."
  value = {
    no_public_endpoint         = azurerm_container_app_environment.this.internal_load_balancer_enabled && azurerm_container_app_environment.this.public_network_access == "Disabled" && !azurerm_container_app.api.ingress[0].external_enabled
    zone_redundant             = azurerm_container_app_environment.this.zone_redundancy_enabled
    workload_identity          = azurerm_container_app.api.identity[0].type == "UserAssigned"
    no_static_credentials      = alltrue([for registry in azurerm_container_app.api.registry : registry.password_secret_name == null || registry.password_secret_name == ""])
    encrypted_between_services = azurerm_container_app_environment.this.mutual_tls_enabled
    logs_to_workspace          = azurerm_container_app_environment.this.log_analytics_workspace_id == var.log_analytics_workspace_id
    at_least_three_replicas    = azurerm_container_app.api.template[0].min_replicas >= 3
  }
}

output "platform_id" {
  description = "Resource id of the Container Apps environment."
  value       = azurerm_container_app_environment.this.id
}
