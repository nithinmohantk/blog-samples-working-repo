# Pins the provider the tests run against. Hashes are added by "terraform init".

provider "registry.terraform.io/hashicorp/aws" {
  version     = "6.63.0"
  constraints = "~> 6.0"
}
