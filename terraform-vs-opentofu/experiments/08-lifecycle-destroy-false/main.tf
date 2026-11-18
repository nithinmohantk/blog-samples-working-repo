# Removing this resource from configuration should forget it, not destroy it.
resource "terraform_data" "record" {
  input = "a"

  lifecycle {
    destroy = false
  }
}
