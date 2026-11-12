resource "terraform_data" "record" {
  input = "a"
}

output "id" {
  value = terraform_data.record.id
}
