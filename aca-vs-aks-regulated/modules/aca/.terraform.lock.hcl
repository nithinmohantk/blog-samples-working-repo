# Pins the provider the tests run against. Hashes are added by "terraform init".

provider "registry.terraform.io/hashicorp/azurerm" {
  version     = "5.2.0"
  constraints = "~> 5.0"
}
