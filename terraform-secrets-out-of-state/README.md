# Keeping secrets out of Terraform state

Sample for the dataa.dev article "[Keeping Secrets Out of Terraform State: Ephemeral Resources and Write-Only Arguments](https://www.dataa.dev/2026/01/10/keeping-secrets-out-of-terraform-state-ephemeral-resources-write-only-arguments/)".

Four small configurations, applied with Terraform and with OpenTofu against a local Secrets Manager
emulator (moto). After each run a script reads the secret back from the emulator and searches every file
the tool wrote for it.

Nothing here calls AWS. The access keys in the scripts are throwaway values the emulator ignores.

| Path | What it is |
| --- | --- |
| `classic/` | A managed `random_password` passed to `secret_string`: the pattern being replaced |
| `ephemeral/` | An ephemeral `random_password` passed to `secret_string_wo`, rotated by a version number |
| `ephemeral/tests/` | Module tests against a mocked AWS provider |
| `variable/` | An existing secret passed in through an ephemeral input variable |
| `misuse/` | An ephemeral value sent to an ordinary output, which both tools refuse |
| `migrate/after.tf` | Replaces `classic/main.tf` to move an existing secret to a write-only argument |
| `probe/` | Records how each tool presents a write-only argument to a mocked-plan test |
| `run_experiments.py`, `ci.sh` | Run all of it and record the observations |

## Run

    pip install "moto[server]" boto3
    moto_server -H 127.0.0.1 -p 5000 &
    python run_experiments.py "$(which terraform)" "$(which tofu)" out

## What was verified

GitHub Actions, `ubuntu-latest`: Terraform 1.14.3, OpenTofu 1.11.0, AWS provider 6.15.0, random provider
3.7.2, moto 5.2.5. Outputs of the latest run are on the `ci-results-terraform` branch under
`terraform-secrets-out-of-state/`. Both tools gave the same result in every row but the last.

| Observation | Terraform 1.14.3 | OpenTofu 1.11.0 |
| --- | --- | --- |
| Classic: password in the state file | 2 times | 2 times |
| Classic: password in the JSON of the next plan | present | present |
| Ephemeral: password anywhere on disk after apply | nowhere | nowhere |
| Ephemeral: password in the JSON of the next plan | absent | absent |
| Ephemeral: state holds for the write-only pair | value null, version 1 | value null, version 1 |
| Ephemeral resource has an entry in state | no | no |
| Second plan with the same version | no changes | no changes |
| Stored password after re-applying the same version | unchanged | unchanged |
| Plan for version 2 | 1 to add, 1 to destroy | 1 to add, 1 to destroy |
| Stored password after version 2 | changed | changed |
| Variable: token in the saved plan file or its JSON | absent | absent |
| Variable: applying the saved plan without the token | refused | refused |
| Variable: applying the saved plan with the token supplied again | applies | applies |
| Misuse: ephemeral value in an ordinary output | refused | refused |
| Migrate: plan | 1 to add, 2 to destroy | 1 to add, 2 to destroy |
| Migrate: old password in the new state file | absent | absent |
| Migrate: old password in the state backup | present | present |
| Module tests against a mocked AWS provider | 2 passed | 2 passed |
| Probe: write-only value reads as null in a mocked plan | yes | no |

## What this does not show

- moto is an emulator. The provider's behaviour against the real service, including IAM and KMS, was not
  exercised.
- Only `aws_secretsmanager_secret_version` was tried. Each provider decides which arguments are write-only
  and how its version argument behaves.
- Local state only. Remote backends keep earlier state versions, which is where an old secret survives a
  migration.
