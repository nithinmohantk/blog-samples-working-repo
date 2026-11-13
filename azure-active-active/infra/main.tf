# The global tier of an active-active API on Azure: a multi-region-write Cosmos DB account, and Front Door
# probing and balancing the regional APIs. The regional tier (the container platform and the API itself)
# is deployed once per region by its own module.

locals {
  tags = {
    workload   = var.name
    managed-by = "terraform"
  }
}

resource "azurerm_cosmosdb_account" "this" {
  name                = "cosmos-${var.name}"
  resource_group_name = var.resource_group_name
  location            = var.regions[0]
  offer_type          = "Standard"
  kind                = "GlobalDocumentDB"

  # Every region accepts writes. Strong consistency is not available in this mode.
  multiple_write_locations_enabled = true
  automatic_failover_enabled       = true

  local_authentication_disabled = true
  public_network_access_enabled = false

  consistency_policy {
    consistency_level = "Session"
  }

  dynamic "geo_location" {
    for_each = var.regions

    content {
      location          = geo_location.value
      failover_priority = geo_location.key
      zone_redundant    = true
    }
  }

  tags = local.tags
}

resource "azurerm_cosmosdb_sql_database" "this" {
  name                = "bookings"
  resource_group_name = var.resource_group_name
  account_name        = azurerm_cosmosdb_account.this.name
}

resource "azurerm_cosmosdb_sql_container" "bookings" {
  name                = "bookings"
  resource_group_name = var.resource_group_name
  account_name        = azurerm_cosmosdb_account.this.name
  database_name       = azurerm_cosmosdb_sql_database.this.name
  partition_key_paths = ["/slotId"]

  # Custom mode with no stored procedure sends every conflict to the conflicts feed, where the application
  # applies its own rule and records a compensation. The default, last writer wins, resolves silently.
  conflict_resolution_policy {
    mode = "Custom"
  }
}

resource "azurerm_cdn_frontdoor_profile" "this" {
  name                = "afd-${var.name}"
  resource_group_name = var.resource_group_name
  sku_name            = "Premium_AzureFrontDoor"
  tags                = local.tags
}

resource "azurerm_cdn_frontdoor_endpoint" "this" {
  name                     = "api-${var.name}"
  cdn_frontdoor_profile_id = azurerm_cdn_frontdoor_profile.this.id
  tags                     = local.tags
}

resource "azurerm_cdn_frontdoor_origin_group" "api" {
  name                     = "regional-apis"
  cdn_frontdoor_profile_id = azurerm_cdn_frontdoor_profile.this.id
  session_affinity_enabled = false

  # Probe readiness, not liveness: a region whose database is unreachable must leave rotation.
  health_probe {
    protocol            = "Https"
    request_type        = "GET"
    path                = "/ready"
    interval_in_seconds = 30
  }

  load_balancing {
    sample_size                        = 4
    successful_samples_required        = 3
    additional_latency_in_milliseconds = 50
  }
}

resource "azurerm_cdn_frontdoor_origin" "api" {
  for_each = toset(var.regions)

  name                           = "api-${each.key}"
  cdn_frontdoor_origin_group_id  = azurerm_cdn_frontdoor_origin_group.api.id
  enabled                        = true
  host_name                      = var.origin_host_names[each.key]
  origin_host_header             = var.origin_host_names[each.key]
  certificate_name_check_enabled = true

  # Equal priority and weight is what makes this active-active. A higher priority number would make
  # that region a standby.
  priority = 1
  weight   = 500
}

resource "azurerm_cdn_frontdoor_route" "api" {
  name                          = "api"
  cdn_frontdoor_endpoint_id     = azurerm_cdn_frontdoor_endpoint.this.id
  cdn_frontdoor_origin_group_id = azurerm_cdn_frontdoor_origin_group.api.id
  cdn_frontdoor_origin_ids      = [for origin in azurerm_cdn_frontdoor_origin.api : origin.id]

  patterns_to_match      = ["/*"]
  supported_protocols    = ["Https"]
  forwarding_protocol    = "HttpsOnly"
  https_redirect_enabled = false
  link_to_default_domain = true
}
