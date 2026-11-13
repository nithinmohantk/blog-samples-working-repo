# The same regulated API platform on AKS Standard: a private, zone-spread cluster on a landing-zone subnet,
# Entra-only access, workload identity, Cilium network policy, Azure Policy, Defender, and automatic
# upgrades inside maintenance windows. The workload itself is Kubernetes manifests, which are not shown.

locals {
  prefix = "${var.name}-${var.environment}"

  tags = {
    workload    = var.name
    environment = var.environment
    managed-by  = "terraform"
  }
}

resource "azurerm_user_assigned_identity" "cluster" {
  name                = "id-${local.prefix}-aks"
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = local.tags
}

resource "azurerm_kubernetes_cluster" "this" {
  name                = "aks-${local.prefix}"
  resource_group_name = var.resource_group_name
  location            = var.location
  dns_prefix          = "aks-${local.prefix}"
  kubernetes_version  = var.kubernetes_version
  sku_tier            = "Standard"

  # No public API server, no local accounts, no static credentials.
  private_cluster_enabled             = true
  private_cluster_public_fqdn_enabled = false
  local_account_disabled              = true

  azure_active_directory_role_based_access_control {
    tenant_id              = var.tenant_id
    azure_rbac_enabled     = true
    admin_group_object_ids = var.admin_group_object_ids
  }

  oidc_issuer_enabled       = true
  workload_identity_enabled = true

  # Patching is yours on AKS Standard. These settings hand the routine part to the platform.
  automatic_upgrade_channel = "patch"
  node_os_upgrade_channel   = "NodeImage"

  maintenance_window_auto_upgrade {
    frequency   = "Weekly"
    interval    = 1
    day_of_week = "Sunday"
    start_time  = "02:00"
    duration    = 4
    utc_offset  = "+00:00"
  }

  maintenance_window_node_os {
    frequency   = "Weekly"
    interval    = 1
    day_of_week = "Sunday"
    start_time  = "02:00"
    duration    = 4
    utc_offset  = "+00:00"
  }

  azure_policy_enabled             = true
  image_cleaner_enabled            = true
  image_cleaner_interval_hours     = 48

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.cluster.id]
  }

  default_node_pool {
    name                         = "system"
    vm_size                      = "Standard_D4ds_v5"
    node_count                   = 3
    zones                        = ["1", "2", "3"]
    vnet_subnet_id               = var.subnet_id
    os_sku                       = "AzureLinux"
    only_critical_addons_enabled = true

    upgrade_settings {
      max_surge = "33%"
    }
  }

  network_profile {
    network_plugin      = "azure"
    network_plugin_mode = "overlay"
    network_data_plane  = "cilium"
    network_policy      = "cilium"
    outbound_type       = "userDefinedRouting"
  }

  microsoft_defender {
    log_analytics_workspace_id = var.log_analytics_workspace_id
  }

  oms_agent {
    log_analytics_workspace_id      = var.log_analytics_workspace_id
    msi_auth_for_monitoring_enabled = true
  }

  key_vault_secrets_provider {
    secret_rotation_enabled = true
  }

  tags = local.tags
}

resource "azurerm_kubernetes_cluster_node_pool" "workload" {
  name                  = "workload"
  kubernetes_cluster_id = azurerm_kubernetes_cluster.this.id
  vm_size               = "Standard_D4ds_v5"
  mode                  = "User"
  os_sku                = "AzureLinux"
  zones                 = ["1", "2", "3"]
  vnet_subnet_id        = var.subnet_id

  auto_scaling_enabled = true
  min_count            = 3
  max_count            = 9

  upgrade_settings {
    max_surge = "33%"
  }

  tags = local.tags
}
