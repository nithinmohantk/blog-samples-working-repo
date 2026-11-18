# A module that states the Terraform release it was written for.
terraform {
  required_version = ">= 1.16.0"
}

resource "terraform_data" "record" {
  input = "a"
}
