# A value that may be used during a run and is never written to state or plan.
variable "token" {
  type      = string
  ephemeral = true
  default   = "not-a-real-token"
}

resource "terraform_data" "record" {
  input = "a"

  lifecycle {
    precondition {
      condition     = length(var.token) > 0
      error_message = "A token is required."
    }
  }
}
