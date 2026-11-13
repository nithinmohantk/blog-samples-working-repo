# No Azure subscription: the provider is mocked, with well-formed ids for the resources other resources refer to.

mock_provider "azurerm" {
  mock_resource "azurerm_cdn_frontdoor_profile" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-mock/providers/Microsoft.Cdn/profiles/afd-mock"
    }
  }

  mock_resource "azurerm_cdn_frontdoor_endpoint" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-mock/providers/Microsoft.Cdn/profiles/afd-mock/afdEndpoints/api-mock"
    }
  }

  mock_resource "azurerm_cdn_frontdoor_origin_group" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-mock/providers/Microsoft.Cdn/profiles/afd-mock/originGroups/regional-apis"
    }
  }

  mock_resource "azurerm_cdn_frontdoor_origin" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-mock/providers/Microsoft.Cdn/profiles/afd-mock/originGroups/regional-apis/origins/api-mock"
    }
  }
}

variables {
  name                = "bookings"
  resource_group_name = "rg-bookings-global"
  regions             = ["northeurope", "westeurope"]
  origin_host_names = {
    northeurope = "ca-bookings-api.internal.northeurope.example.net"
    westeurope  = "ca-bookings-api.internal.westeurope.example.net"
  }
}

run "every_region_accepts_writes" {
  command = plan

  assert {
    condition     = azurerm_cosmosdb_account.this.multiple_write_locations_enabled
    error_message = "Multi-region writes must be enabled."
  }

  assert {
    condition     = length(azurerm_cosmosdb_account.this.geo_location) == 2 && alltrue([for location in azurerm_cosmosdb_account.this.geo_location : location.zone_redundant])
    error_message = "Both regions must be database locations, each zone redundant."
  }
}

run "database_has_no_keys_and_no_public_endpoint" {
  command = plan

  assert {
    condition     = azurerm_cosmosdb_account.this.local_authentication_disabled && !azurerm_cosmosdb_account.this.public_network_access_enabled
    error_message = "Key-based authentication and public network access must be off."
  }
}

run "conflicts_go_to_the_application" {
  command = plan

  assert {
    condition     = azurerm_cosmosdb_sql_container.bookings.conflict_resolution_policy[0].mode == "Custom"
    error_message = "Conflicts must not be resolved silently by last writer wins."
  }
}

run "regions_are_equal_peers" {
  command = plan

  assert {
    condition     = length(azurerm_cdn_frontdoor_origin.api) == 2 && alltrue([for origin in azurerm_cdn_frontdoor_origin.api : origin.priority == 1 && origin.weight == 500])
    error_message = "Every region must have the same priority and weight."
  }
}

run "the_probe_asks_for_readiness" {
  command = plan

  assert {
    condition     = azurerm_cdn_frontdoor_origin_group.api.health_probe[0].path == "/ready" && azurerm_cdn_frontdoor_origin_group.api.health_probe[0].protocol == "Https"
    error_message = "Front Door must probe the readiness endpoint over HTTPS."
  }

  assert {
    condition     = azurerm_cdn_frontdoor_origin_group.api.session_affinity_enabled == false
    error_message = "Session affinity would pin clients to a region and defeat failover."
  }
}

run "rejects_a_single_region" {
  command = plan

  variables {
    regions = ["northeurope"]
  }

  expect_failures = [var.regions]
}

run "rejects_a_region_with_no_origin" {
  command = plan

  variables {
    regions = ["northeurope", "francecentral"]
  }

  expect_failures = [var.origin_host_names]
}
