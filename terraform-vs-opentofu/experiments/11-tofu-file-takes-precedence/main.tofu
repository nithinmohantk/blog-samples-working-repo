# OpenTofu reads this file and ignores main.tf beside it. Terraform does not know the extension.
output "loaded_from" {
  value = "main.tofu"
}
