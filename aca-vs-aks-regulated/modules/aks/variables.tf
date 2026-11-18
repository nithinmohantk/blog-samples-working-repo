variable "name" {
  description = "Workload name, lower-case letters and digits."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9]{2,11}$", var.name))
    error_message = "name must be 3 to 12 lower-case letters and digits, starting with a letter."
  }
}

variable "environment" {
  description = "Deployment environment."
  type        = string

  validation {
    condition     = contains(["dev", "test", "prod"], var.environment)
    error_message = "environment must be dev, test or prod."
  }
}

variable "location" {
  description = "Azure region."
  type        = string
}

variable "resource_group_name" {
  description = "Existing resource group for the platform resources."
  type        = string
}

variable "subnet_id" {
  description = "Existing subnet from the landing zone, with a route table that sends 0.0.0.0/0 to the firewall."
  type        = string
}

variable "log_analytics_workspace_id" {
  description = "Existing Log Analytics workspace for platform and security logs."
  type        = string
}

variable "tenant_id" {
  description = "Microsoft Entra tenant that authenticates cluster users."
  type        = string
}

variable "admin_group_object_ids" {
  description = "Entra groups that administer the cluster."
  type        = list(string)
}

variable "kubernetes_version" {
  description = "Kubernetes minor version. Patch versions follow the upgrade channel."
  type        = string
  default     = "1.33"
}
