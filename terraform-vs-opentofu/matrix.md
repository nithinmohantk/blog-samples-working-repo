| Experiment | Terraform | OpenTofu |
| --- | --- | --- |
| Plain configuration (control) | pass | pass |
| State and plan encryption in the terraform block | fail at init | pass |
| Variable in the backend block | fail at init | pass |
| for_each on a provider configuration | fail at init | pass |
| apply -exclude=ADDRESS | fail at apply | pass |
| lifecycle { enabled = ... } | fail at init | pass |
| prevent_destroy set from a variable | fail at init | pass |
| lifecycle { destroy = false } | pass | fail at destroy |
| import block inside a child module | pass | fail at init |
| ephemeral input variable | pass | pass |
| main.tofu beside main.tf | pass | pass |
| required_version = ">= 1.16.0" | pass | pass |
| required_version = ">= 99.0.0" in a .tf file | fail at init | pass |
| language { compatible_with { opentofu = ">= 99.0.0" } } | fail at init | fail at init |
| required_version = ">= 99.0.0" in a .tofu file | pass | fail at init |
| variable with const = true | pass | pass |
| variable with deprecated = "..." | pass | pass |
| state show -json | pass | pass |
| contains() with a null element | pass | pass |
| convert(value, type) | pass | pass |
| Provider address written to the lock file | pass | pass |
| State written by this tool, planned by the other | pass | pass |
| Encrypted state written by this tool, planned by the other | fail at init | fail at the other tool's init |
| override_during = plan in a test | pass | fail at init |
