# Zero-or-one instance of a resource without count and without an index on every reference.
variable "with_audit" {
  type    = bool
  default = false
}

resource "terraform_data" "audit" {
  input = "audit"

  lifecycle {
    enabled = var.with_audit
  }
}
