output "has_null" {
  value = contains(["a", null], null)
}
