# GENERATED from contract/contract.tftest.hcl.tmpl by contract/render.py. Do not edit this copy.
# The same assertions run against every implementation of the contract. They read outputs only.

mock_provider "azurerm" {}

variables {
  name          = "records"
  environment   = "dev"
  region        = "northeurope"
  address_space = "10.40.0.0/20"
}

run "subnets_are_named_and_sized_the_same_way" {
  command = plan

  assert {
    condition     = output.subnet_cidrs == { "private-1" = "10.40.0.0/22", "private-2" = "10.40.4.0/22" }
    error_message = "Two /22 subnets named private-1 and private-2 are expected from a /20."
  }
}

run "subnet_count_is_honoured" {
  command = plan

  variables {
    subnet_count = 4
  }

  assert {
    condition     = keys(output.subnet_cidrs) == ["private-1", "private-2", "private-3", "private-4"]
    error_message = "Four subnets are expected."
  }

  assert {
    condition     = output.subnet_cidrs["private-4"] == "10.40.12.0/22"
    error_message = "The fourth subnet must be the last quarter of the address space."
  }
}

run "tags_carry_workload_and_environment" {
  command = plan

  variables {
    tags = { cost-centre = "cc-1042" }
  }

  assert {
    condition     = output.tags == { "cost-centre" = "cc-1042", "environment" = "dev", "managed-by" = "terraform", "workload" = "records" }
    error_message = "Caller tags must be merged with the standard three."
  }
}

run "identifiers_are_exposed_after_apply" {
  command = apply

  assert {
    condition     = length(output.network_id) > 0 && length(output.log_store_id) > 0
    error_message = "network_id and log_store_id must be set."
  }

  assert {
    condition     = keys(output.subnet_ids) == keys(output.subnet_cidrs)
    error_message = "There must be one subnet id for each subnet CIDR, under the same names."
  }
}

run "rejects_an_address_space_that_is_too_small" {
  command = plan

  variables {
    address_space = "10.40.0.0/26"
  }

  expect_failures = [var.address_space]
}

run "rejects_text_that_is_not_a_cidr" {
  command = plan

  variables {
    address_space = "ten dot forty"
  }

  expect_failures = [var.address_space]
}

run "rejects_five_subnets" {
  command = plan

  variables {
    subnet_count = 5
  }

  expect_failures = [var.subnet_count]
}

run "rejects_short_log_retention" {
  command = plan

  variables {
    log_retention_days = 30
  }

  expect_failures = [var.log_retention_days]
}

run "rejects_a_name_with_a_hyphen" {
  command = plan

  variables {
    name = "patient-records"
  }

  expect_failures = [var.name]
}
