# A regulated API on Azure Container Apps. The platform is an internal, zone-redundant environment on a
# landing-zone subnet; the workload is one container app with a managed identity and no public ingress.

locals {
  prefix = "${var.name}-${var.environment}"

  tags = {
    workload    = var.name
    environment = var.environment
    managed-by  = "terraform"
  }
}

resource "azurerm_user_assigned_identity" "api" {
  name                = "id-${local.prefix}-api"
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = local.tags
}

resource "azurerm_container_app_environment" "this" {
  name                = "cae-${local.prefix}"
  resource_group_name = var.resource_group_name
  location            = var.location

  infrastructure_subnet_id       = var.subnet_id
  internal_load_balancer_enabled = true
  public_network_access          = "Disabled"
  zone_redundancy_enabled        = true
  mutual_tls_enabled             = true
  log_analytics_workspace_id     = var.log_analytics_workspace_id

  workload_profile {
    name                  = "dedicated"
    workload_profile_type = "D4"
    minimum_count         = 3
    maximum_count         = 6
  }

  tags = local.tags
}

resource "azurerm_container_app" "api" {
  name                         = "ca-${local.prefix}-api"
  resource_group_name          = var.resource_group_name
  container_app_environment_id = azurerm_container_app_environment.this.id
  revision_mode                = "Single"
  workload_profile_name        = "dedicated"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.api.id]
  }

  # The image is pulled with the managed identity: no registry password exists.
  registry {
    server   = var.registry_server
    identity = azurerm_user_assigned_identity.api.id
  }

  ingress {
    external_enabled           = false
    allow_insecure_connections = false
    target_port                = 8080
    transport                  = "http"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 3
    max_replicas = 10

    container {
      name   = "api"
      image  = var.image
      cpu    = 0.5
      memory = "1Gi"

      liveness_probe {
        transport = "HTTP"
        port      = 8080
        path      = "/healthz"
      }

      readiness_probe {
        transport = "HTTP"
        port      = 8080
        path      = "/ready"
      }
    }
  }

  tags = local.tags
}
