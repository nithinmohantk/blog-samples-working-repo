# Testing infrastructure code in CI, with no cloud account

Sample for the dataa.dev article "Testing Infrastructure Code: terraform test, Mock Providers and a Policy Gate in CI".

A Terraform module for an S3 bucket that holds clinical documents, tested three ways without touching AWS:
unit tests against a mocked provider, deliberate defects that the tests must catch, and a policy gate over
the machine-readable plan.

The bucket names, account ids and key ARNs are made up. Nothing here is ever applied to a real account.

| Path | What it is |
| --- | --- |
| `modules/secure-bucket` | The module: bucket, versioning, SSE-KMS, public access block, lifecycle, TLS-only policy |
| `modules/secure-bucket/tests` | 14 unit tests that run unchanged on Terraform and OpenTofu |
| `modules/secure-bucket/tests-terraform-only` | A test that uses `override_during = plan`, which OpenTofu 1.12 rejects |
| `modules/secure-bucket/tests-experiments` | A test that is expected to fail, kept as a record of a trap |
| `mutations.json`, `mutate.py` | Ten deliberate defects, applied one at a time to a copy of the module |
| `examples/compliant`, `examples/noncompliant` | Two root configurations to plan |
| `policy/check_plan.py` | The policy gate over `show -json` output, with tests |
| `ci.sh` | Runs all of it; this is what the workflow calls |

## Run

Needs Terraform 1.9 or later (the workflow pins 1.16.3), OpenTofu for the comparison, and Python 3.11 or later.
No AWS credentials.

    cd modules/secure-bucket && terraform init && terraform test
    ./ci.sh out

## What was verified

GitHub Actions, `ubuntu-latest`, Terraform 1.16.3, OpenTofu 1.12.6, AWS provider 6.63.0, commit `e081e6d`:
<https://github.com/nithinmohantk/blog-samples-working-repo/actions/runs/43295858286>. Outputs of the latest run
are on the `ci-results-terraform` branch.

| Check | Result |
| --- | --- |
| `terraform test`, portable suite | 14 passed, 0 failed |
| `tofu test`, same files | 14 passed, 0 failed |
| Terraform-only suite on Terraform | 1 passed |
| Terraform-only suite on OpenTofu 1.12.6 | Refused: `An argument named "override_during" is not expected here` |
| Ten deliberate defects | All ten caught, each by a named test |
| Policy gate on the plan of the module | 0 findings, exit 0 |
| Policy gate on the plan of a hand-written bucket | 4 findings, exit 1 |
| Policy gate on a destroy of a clinical bucket (hand-written plan fixture) | 1 finding, exit 1 |
| Policy gate tests | 9 of 9 |

## Findings

* `override_during = plan` on a mocked provider, together with `defaults` for only some attributes of a resource,
  broke an apply run: Terraform reported "Provider produced inconsistent final plan" 14 times, once for each
  remaining computed attribute of `aws_s3_bucket`, because a different random value was generated at plan and at
  apply. The same test with no `defaults` block passed.
* OpenTofu 1.12.6 does not accept `override_during`. A suite that asserts on computed values in apply runs and on
  configured values in plan runs works on both tools.
* A mutation that replaced a validation condition with `true` did not test anything: Terraform rejects a
  validation that does not refer to its variable. The defects in `mutations.json` are ones that still compile.
* `terraform init` accepted a hand-written lock file entry with a version and no hashes, installed that version,
  and added the hashes.

Not verified: anything against a real AWS account, so nothing here shows that the provider or AWS accepts the
configuration at apply time. The destroy plan is a hand-written fixture, because a real one needs existing state.
