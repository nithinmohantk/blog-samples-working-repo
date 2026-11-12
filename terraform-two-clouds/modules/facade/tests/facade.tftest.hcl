# A caller that only wants AWS still has to satisfy the Azure provider, and the other way round.

mock_provider "aws" {}
mock_provider "azurerm" {}

variables {
  name          = "records"
  environment   = "dev"
  address_space = "10.40.0.0/20"
}

run "aws_through_the_facade" {
  command = apply

  variables {
    cloud  = "aws"
    region = "eu-west-1"
  }

  assert {
    condition     = length(module.aws) == 1 && length(module.azure) == 0
    error_message = "Only the AWS implementation should be instantiated."
  }

  assert {
    condition     = output.subnet_cidrs["private-2"] == "10.40.4.0/22"
    error_message = "The facade must pass the contract's outputs through."
  }
}

run "azure_through_the_facade" {
  command = apply

  variables {
    cloud  = "azure"
    region = "northeurope"
  }

  assert {
    condition     = length(module.aws) == 0 && length(module.azure) == 1
    error_message = "Only the Azure implementation should be instantiated."
  }

  assert {
    condition     = output.subnet_cidrs["private-2"] == "10.40.4.0/22"
    error_message = "The facade must pass the contract's outputs through."
  }
}
