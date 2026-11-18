# Marking an input as deprecated so callers are warned.
variable "old_name" {
  type       = string
  default    = null
  deprecated = "Use new_name."
}

variable "new_name" {
  type    = string
  default = "a"
}

resource "terraform_data" "record" {
  input = coalesce(var.old_name, var.new_name)
}
