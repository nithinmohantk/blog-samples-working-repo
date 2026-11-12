# An import block that lives with the resource it imports, inside a child module.
import {
  to = terraform_data.adopted
  id = "existing-object-id"
}

resource "terraform_data" "adopted" {}
