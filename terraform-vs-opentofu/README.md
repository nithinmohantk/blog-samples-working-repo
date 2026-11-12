# Terraform and OpenTofu on the same configurations

Sample for the dataa.dev article "Terraform 1.16 and OpenTofu 1.13: Where They Have Diverged".

Twenty-four small configurations, each run on both tools. The harness records whether each tool accepts the
configuration, at which step it refuses, and the first error it prints. A refusal is a result, not a failure
of the sample: the run fails only when a result differs from what `experiments.json` records, which is how a
new release that changes behaviour shows up.

Every experiment uses the built-in `terraform_data` resource or the `hashicorp/local` provider. No cloud
account is involved.

| Path | What it is |
| --- | --- |
| `experiments/` | One folder per experiment |
| `experiments.json` | Title, steps and the recorded result for each tool |
| `run_matrix.py` | Runs every experiment on both binaries and writes `matrix.json` and `matrix.md` |
| `ci.sh` | Downloads the two pinned CLIs and runs the matrix |

## Run

    python run_matrix.py "$(command -v terraform)" "$(command -v tofu)" out

## What was observed

GitHub Actions, `ubuntu-latest`, Terraform 1.16.5 and OpenTofu 1.13.1, commit `b6faa0c`:
<https://github.com/nithinmohantk/blog-samples-working-repo/actions/runs/43300370959>. 24 experiments,
0 results different from the recorded ones.

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

Details behind some rows:

* **State encryption.** With the `encryption` block, the OpenTofu state file did not contain the test value and
  did contain `encrypted_data`. The control state on both tools held the value in clear text.
* **`lifecycle { destroy = false }`.** Both tools accept it. `terraform destroy` exits 0. `tofu destroy` exits
  non-zero with "Destroy was successful but left behind forgotten instances".
* **`required_version`.** OpenTofu 1.13.1 did not enforce a `required_version` written in a `.tf` file, even
  `>= 99.0.0`. It enforced the same constraint in a `.tofu` file, and a `language` block.
* **`main.tofu` beside `main.tf`.** Terraform reported `loaded_from = main.tf`, OpenTofu `main.tofu`.
* **Lock file.** Terraform records `registry.terraform.io/hashicorp/local`, OpenTofu
  `registry.opentofu.org/hashicorp/local`.
* **State handover.** Plain state written by either tool was planned by the other with no changes. Encrypted
  state cannot be handed to Terraform: the configuration that reads it is refused.

Not covered: HCP Terraform, Stacks, actions, list resources and queries, OCI registries, and anything that
needs a cloud provider. Those are described in the article from release notes only.
