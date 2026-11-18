# A variable used in the backend configuration, which is evaluated before the rest of the module.
variable "state_dir" {
  type    = string
  default = "state"
}

terraform {
  backend "local" {
    path = "${var.state_dir}/terraform.tfstate"
  }
}

resource "terraform_data" "record" {
  input = "a"
}
