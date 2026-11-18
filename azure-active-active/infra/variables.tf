variable "name" {
  description = "Workload name, lower-case letters and digits."
  type        = string
}

variable "resource_group_name" {
  description = "Existing resource group for the global resources."
  type        = string
}

variable "regions" {
  description = "The regions that serve traffic and accept writes, in order. Each needs a deployed API."
  type        = list(string)

  validation {
    condition     = length(var.regions) >= 2 && length(distinct(var.regions)) == length(var.regions)
    error_message = "Active-active needs at least two distinct regions."
  }
}

variable "origin_host_names" {
  description = "Host name of the API in each region, by region name."
  type        = map(string)

  validation {
    condition     = alltrue([for region in var.regions : contains(keys(var.origin_host_names), region)])
    error_message = "origin_host_names needs an entry for every region."
  }
}
