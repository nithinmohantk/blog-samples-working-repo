# The same provider requirement. What does each tool write into the lock file?
terraform {
  required_providers {
    local = {
      source  = "hashicorp/local"
      version = "2.5.3"
    }
  }
}

resource "local_file" "marker" {
  filename = "${path.module}/marker.txt"
  content  = "a"
}
