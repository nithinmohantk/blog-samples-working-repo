# The OpenTofu way to state compatibility: a language block.
language {
  compatible_with {
    opentofu = ">= 99.0.0"
  }
}

resource "terraform_data" "record" {
  input = "a"
}
