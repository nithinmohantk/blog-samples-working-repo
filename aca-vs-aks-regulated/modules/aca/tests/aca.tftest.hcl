# No Azure subscription: the provider is mocked. Identifiers passed between resources are well-formed,
# because the provider checks their format even when mocked.

mock_provider "azurerm" {
  mock_resource "azurerm_user_assigned_identity" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-mock/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-mock"
    }
  }

  mock_resource "azurerm_container_app_environment" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-mock/providers/Microsoft.App/managedEnvironments/cae-mock"
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
  image                      = "crrecordsprod.azurecr.io/records-api:1.4.2"
  registry_server            = "crrecordsprod.azurecr.io"
}

run "every_baseline_control_but_one_is_a_setting" {
  command = apply

  assert {
    condition     = alltrue(values(output.controls))
    error_message = "A baseline control is not configured: ${jsonencode(output.controls)}"
  }
}

run "environment_is_internal_and_closed_to_the_internet" {
  command = plan

  assert {
    condition     = azurerm_container_app_environment.this.internal_load_balancer_enabled && azurerm_container_app_environment.this.public_network_access == "Disabled"
    error_message = "The environment must be internal with public network access disabled."
  }
}

run "app_ingress_is_internal_and_https_only" {
  command = plan

  assert {
    condition     = azurerm_container_app.api.ingress[0].external_enabled == false && azurerm_container_app.api.ingress[0].allow_insecure_connections == false
    error_message = "Ingress must be limited to the virtual network and must not accept plain HTTP."
  }
}

run "image_is_pulled_with_the_managed_identity" {
  command = apply

  assert {
    condition     = azurerm_container_app.api.registry[0].identity == azurerm_user_assigned_identity.api.id
    error_message = "The registry must be accessed with the app's managed identity."
  }
}

run "dedicated_profile_spans_three_zones_worth_of_nodes" {
  command = plan

  assert {
    condition     = one(azurerm_container_app_environment.this.workload_profile).minimum_count >= 3 && azurerm_container_app_environment.this.zone_redundancy_enabled
    error_message = "A zone-redundant environment needs at least three nodes in the dedicated profile."
  }
}

run "rejects_an_unknown_environment" {
  command = plan

  variables {
    environment = "production"
  }

  expect_failures = [var.environment]
}
