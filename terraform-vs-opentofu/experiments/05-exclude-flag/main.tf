# Apply everything except one resource, from the command line.
resource "terraform_data" "kept" {
  input = "kept"
}

resource "terraform_data" "skipped" {
  input = "skipped"
}
