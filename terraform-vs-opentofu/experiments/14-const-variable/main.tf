# A variable declared as usable where values must be known before evaluation starts.
variable "state_dir" {
  type    = string
  default = "state"
  const   = true
}

resource "terraform_data" "record" {
  input = var.state_dir
}
