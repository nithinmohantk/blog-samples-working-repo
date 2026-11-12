# An override whose values are available while planning.
override_resource {
  target          = terraform_data.record
  override_during = plan
  values = {
    id = "fixed-id"
  }
}

run "plan_sees_the_override" {
  command = plan

  assert {
    condition     = output.id == "fixed-id"
    error_message = "The overridden id should be known during plan."
  }
}
