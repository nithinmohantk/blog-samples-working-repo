# One contract, two clouds: a network baseline on AWS and Azure

Sample for the dataa.dev article "One Contract, Two Clouds: A Network Baseline on AWS and Azure with Terraform".

The same slice of a landing zone, a private network with logging, built twice: once from AWS resources and
once from Azure resources. The two modules share a contract (inputs, outputs, naming and subnet arithmetic)
and a set of contract tests. They do not share resources, and no module pretends the clouds are the same.

Names, subscriptions and accounts are made up. Nothing here is applied to a real account.

| Path | What it is |
| --- | --- |
| `contract/` | The contract: `variables.tf`, `outputs.tf`, `locals.tf`, the contract test template, and the mock blocks |
| `contract/render.py` | Copies the contract into each implementation; `--check` fails when a copy has drifted |
| `modules/network-baseline-aws` | VPC, private subnets, deny-all default security group, flow logs to an encrypted bucket |
| `modules/network-baseline-azure` | Resource group, virtual network, subnets with no default outbound access, diagnostics to a locked-down storage account |
| `modules/facade` | One module with a `cloud` switch, kept to measure what that design costs |
| `ci.sh` | Runs all of it on Terraform and OpenTofu; this is what the workflow calls |

## Run

Needs Terraform 1.9 or later (the workflow pins 1.16.3) and Python 3.11 or later. No cloud credentials.

    python contract/render.py --check
    cd modules/network-baseline-azure && terraform init && terraform test

## What was verified

GitHub Actions, `ubuntu-latest`, Terraform 1.16.3, OpenTofu 1.12.6, AWS provider 6.63.0, AzureRM provider 5.2.0,
commit `6b778bd`: <https://github.com/nithinmohantk/blog-samples-working-repo/actions/runs/43297687751>.

| Check | Terraform | OpenTofu |
| --- | --- | --- |
| AWS module: 9 contract tests and 4 AWS tests | 13 passed | 13 passed |
| Azure module: the same 9 contract tests and 4 Azure tests | 13 passed | 13 passed |
| Facade: one run per cloud | 2 passed | 2 passed |

| Module | `init` | Providers on disk |
| --- | --- | --- |
| AWS | 5 s | 839 MB |
| Azure | 2 s | 214 MB |
| Facade (both providers) | 6 s | 1,053 MB |

Weakening a rule in one copy of the contract was caught twice: `render.py --check` reported the file as stale,
and the contract test `rejects_short_log_retention` failed.

## Findings

* A mocked provider still validates the format of some values. Generated placeholders failed with
  `"log_destination" ... is an invalid ARN` on AWS and `parsing the StorageAccount ID: the number of segments
  didn't match` on Azure, until the mocks were given well-formed defaults.
* The two tools generate mock values at different times. On Terraform 1.16.3 the format errors appeared only in
  apply runs. On OpenTofu 1.12.6 they appeared in plan runs too, and its placeholders were four characters
  where Terraform's were eight.
* An assertion on a computed set in a plan run fails on Terraform with "Unknown condition value".

Not verified: anything against a real AWS account or Azure subscription. `terraform validate` accepted both
modules against the real provider schemas, which is not the same as either cloud accepting them at apply time.
