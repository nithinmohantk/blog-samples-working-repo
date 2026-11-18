# prevent_destroy decided by an input, for example on in prod and off in dev.
variable "protect" {
  type    = bool
  default = true
}

resource "terraform_data" "record" {
  input = "a"

  lifecycle {
    prevent_destroy = var.protect
  }
}
