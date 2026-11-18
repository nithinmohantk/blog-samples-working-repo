# Pins the providers the tests run against. Hashes are added by "terraform init".

provider "registry.terraform.io/hashicorp/aws" {
  version     = "6.63.0"
  constraints = "~> 6.0"
}

provider "registry.terraform.io/hashicorp/azurerm" {
  version     = "5.2.0"
  constraints = "~> 5.0"
}
