# A constraint no released version of either tool satisfies.
terraform {
  required_version = ">= 99.0.0"
}

resource "terraform_data" "record" {
  input = "a"
}
