# Control: plain configuration both tools must accept. Its state file is the comparison for experiment 02.
resource "terraform_data" "record" {
  input = "patient-index-shard-7"
}

output "stored" {
  value = terraform_data.record.output
}
