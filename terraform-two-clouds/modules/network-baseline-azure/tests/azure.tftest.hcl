# What only the Azure implementation can be asked: the cloud-specific controls.

# --- mock block, kept in step with the contract by contract/render.py ---
# The Azure provider parses resource ids even when it is mocked. Give the mock well-formed ones
# for the two resources whose ids are passed to other resources.
mock_provider "azurerm" {
  mock_resource "azurerm_virtual_network" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-mock/providers/Microsoft.Network/virtualNetworks/vnet-mock"
    }
  }

  mock_resource "azurerm_storage_account" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-mock/providers/Microsoft.Storage/storageAccounts/stmock"
    }
  }
}
# --- mock block, kept in step with the contract by contract/render.py ---

variables {
  name          = "records"
  environment   = "dev"
  region        = "northeurope"
  address_space = "10.40.0.0/20"
}

run "subnets_have_no_default_outbound_access" {
  command = plan

  assert {
    condition     = alltrue([for subnet in azurerm_subnet.private : subnet.default_outbound_access_enabled == false])
    error_message = "Private subnets must not have default outbound access."
  }
}

run "log_storage_is_locked_down" {
  command = plan

  assert {
    condition     = azurerm_storage_account.logs.min_tls_version == "TLS1_2" && azurerm_storage_account.logs.https_traffic_only_enabled
    error_message = "The log storage account must require HTTPS with TLS 1.2 or later."
  }

  assert {
    condition     = azurerm_storage_account.logs.allow_nested_items_to_be_public == false && azurerm_storage_account.logs.shared_access_key_enabled == false
    error_message = "The log storage account must not allow public blobs or shared key access."
  }

  assert {
    condition     = azurerm_storage_account.logs.infrastructure_encryption_enabled
    error_message = "The log storage account must use infrastructure encryption."
  }
}

run "storage_account_name_fits_the_naming_rules" {
  command = plan

  variables {
    name = "longworkload"
  }

  assert {
    condition     = can(regex("^[a-z0-9]{3,24}$", azurerm_storage_account.logs.name))
    error_message = "Storage account names must be 3 to 24 lower-case letters and digits."
  }
}

run "logs_expire_after_the_retention_period" {
  command = plan

  assert {
    condition     = azurerm_storage_management_policy.logs.rule[0].actions[0].base_blob[0].delete_after_days_since_modification_greater_than == 365
    error_message = "Logs must be deleted after the retention period."
  }
}
