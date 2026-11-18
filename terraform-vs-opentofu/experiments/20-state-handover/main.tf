# State written by one tool, then planned by the other. No changes is the only acceptable plan.
resource "terraform_data" "record" {
  input = "patient-index-shard-7"
}
