# Azure implementation of the network baseline contract: a resource group, a virtual network with
# private subnets that have no default outbound access, and diagnostics delivered to a locked-down
# storage account.

resource "azurerm_resource_group" "this" {
  name     = "rg-${local.prefix}-network"
  location = var.region
  tags     = local.tags
}

resource "azurerm_virtual_network" "this" {
  name                = "vnet-${local.prefix}"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  address_space       = [var.address_space]
  tags                = local.tags
}

resource "azurerm_subnet" "private" {
  for_each = local.subnets

  name                            = "snet-${local.prefix}-${each.key}"
  resource_group_name             = azurerm_resource_group.this.name
  virtual_network_name            = azurerm_virtual_network.this.name
  address_prefixes                = [each.value]
  default_outbound_access_enabled = false
}

resource "azurerm_storage_account" "logs" {
  # Storage account names: 3 to 24 lower-case letters and digits, globally unique.
  name                = substr("stnetlogs${var.name}${var.environment}", 0, 24)
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location

  account_tier                     = "Standard"
  account_replication_type         = "GRS"
  min_tls_version                  = "TLS1_2"
  https_traffic_only_enabled       = true
  allow_nested_items_to_be_public  = false
  shared_access_key_enabled        = false
  infrastructure_encryption_enabled = true
  tags                             = local.tags
}

resource "azurerm_storage_management_policy" "logs" {
  storage_account_id = azurerm_storage_account.logs.id

  rule {
    name    = "expire-network-logs"
    enabled = true

    filters {
      blob_types = ["blockBlob", "appendBlob"]
    }

    actions {
      base_blob {
        delete_after_days_since_modification_greater_than = var.log_retention_days
      }
    }
  }
}

resource "azurerm_monitor_diagnostic_setting" "network" {
  name               = "diag-${local.prefix}-network"
  target_resource_id = azurerm_virtual_network.this.id
  storage_account_id = azurerm_storage_account.logs.id

  enabled_log {
    category_group = "allLogs"
  }
}

locals {
  network_id   = azurerm_virtual_network.this.id
  subnet_ids   = { for name, subnet in azurerm_subnet.private : name => subnet.id }
  log_store_id = azurerm_storage_account.logs.id
}
