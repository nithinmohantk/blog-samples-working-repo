# One provider configuration per element of a set, selected per resource instance.
terraform {
  required_providers {
    local = {
      source  = "hashicorp/local"
      version = "2.5.3"
    }
  }
}

variable "regions" {
  type    = set(string)
  default = ["eu-west-1", "eu-central-1"]
}

provider "local" {
  alias    = "by_region"
  for_each = var.regions
}

resource "local_file" "marker" {
  for_each = var.regions
  provider = local.by_region[each.key]

  filename = "${path.module}/out/${each.key}.txt"
  content  = each.key
}
