# No Azure subscription: the provider is mocked. Identifiers passed between resources are well-formed,
# because the provider checks their format even when mocked.

mock_provider "azurerm" {
  mock_resource "azurerm_user_assigned_identity" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-mock/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-mock"
    }
  }

  mock_resource "azurerm_kubernetes_cluster" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-mock/providers/Microsoft.ContainerService/managedClusters/aks-mock"
    }
  }
}

variables {
  name                       = "records"
  environment                = "prod"
  location                   = "northeurope"
  resource_group_name        = "rg-records-prod"
  subnet_id                  = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-mock/providers/Microsoft.Network/virtualNetworks/vnet-mock/subnets/snet-apps"
  log_analytics_workspace_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-mock/providers/Microsoft.OperationalInsights/workspaces/log-mock"
  tenant_id                  = "11111111-1111-1111-1111-111111111111"
  admin_group_object_ids     = ["22222222-2222-2222-2222-222222222222"]
}

run "one_baseline_control_is_not_a_cluster_setting" {
  command = apply

  assert {
    condition     = [for name, met in output.controls : name if !met] == ["encrypted_between_services"]
    error_message = "Expected every control except in-cluster encryption to be configured: ${jsonencode(output.controls)}"
  }
}

run "api_server_is_private_and_entra_only" {
  command = plan

  assert {
    condition     = azurerm_kubernetes_cluster.this.private_cluster_enabled && azurerm_kubernetes_cluster.this.local_account_disabled
    error_message = "The API server must be private and local accounts must be disabled."
  }

  assert {
    condition     = azurerm_kubernetes_cluster.this.azure_active_directory_role_based_access_control[0].azure_rbac_enabled
    error_message = "Kubernetes authorisation must use Azure RBAC."
  }
}

run "egress_leaves_through_the_landing_zone_route" {
  command = plan

  assert {
    condition     = azurerm_kubernetes_cluster.this.network_profile[0].outbound_type == "userDefinedRouting"
    error_message = "Outbound traffic must follow the subnet's route table to the firewall."
  }
}

run "network_policy_engine_is_on" {
  command = plan

  assert {
    condition     = azurerm_kubernetes_cluster.this.network_profile[0].network_policy == "cilium" && azurerm_kubernetes_cluster.this.network_profile[0].network_data_plane == "cilium"
    error_message = "A network policy engine must be enabled so traffic between workloads can be restricted."
  }
}

run "patching_is_automatic_inside_a_window" {
  command = plan

  assert {
    condition     = azurerm_kubernetes_cluster.this.automatic_upgrade_channel == "patch" && azurerm_kubernetes_cluster.this.node_os_upgrade_channel == "NodeImage"
    error_message = "Cluster patch upgrades and node image upgrades must be automatic."
  }

  assert {
    condition     = azurerm_kubernetes_cluster.this.maintenance_window_auto_upgrade[0].day_of_week == "Sunday" && azurerm_kubernetes_cluster.this.maintenance_window_node_os[0].day_of_week == "Sunday"
    error_message = "Upgrades must be confined to the agreed maintenance window."
  }
}

run "policy_and_threat_detection_are_on" {
  command = plan

  assert {
    condition     = azurerm_kubernetes_cluster.this.azure_policy_enabled && length(azurerm_kubernetes_cluster.this.microsoft_defender) == 1
    error_message = "Azure Policy and Defender for Containers must be enabled."
  }
}

run "system_pool_is_reserved_and_spread" {
  command = plan

  assert {
    condition     = azurerm_kubernetes_cluster.this.default_node_pool[0].only_critical_addons_enabled && length(azurerm_kubernetes_cluster.this.default_node_pool[0].zones) == 3
    error_message = "The system pool must run only critical add-ons and span three zones."
  }
}

run "rejects_an_unknown_environment" {
  command = plan

  variables {
    environment = "production"
  }

  expect_failures = [var.environment]
}
