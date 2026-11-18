# Azure Container Apps or AKS for a regulated workload

Sample for the dataa.dev article "Azure Container Apps or AKS for a Regulated Workload: Who Patches What".

The same baseline for a regulated API, written twice in Terraform: once on Azure Container Apps and once on
AKS Standard. Both modules report the same named controls, so the comparison is between two pieces of
configuration and not two slide decks. A small decision script and an ownership ledger sit beside them.

Names, subscriptions and tenants are made up. Nothing here is applied to a real subscription.

| Path | What it is |
| --- | --- |
| `modules/aca` | Internal, zone-redundant Container Apps environment and one app with a managed identity |
| `modules/aks` | Private AKS Standard cluster: Entra-only access, workload identity, Cilium policy, automatic patching in a window |
| `modules/*/tests` | Tests against a mocked provider |
| `decision/decide.py` | A rule-based recommendation from a list of facts about the workload, with tests |
| `decision/ownership.json` | Who does each operational duty on each platform. An assessment, not a contract |
| `measure.py` | Counts resources, arguments and lines in each module |
| `ci.sh` | Runs all of it on Terraform and OpenTofu |

## Run

    cd modules/aca && terraform init && terraform test
    python decision/decide.py decision/requirements-example.json

## What was verified

GitHub Actions, `ubuntu-latest`, Terraform 1.16.3, OpenTofu 1.12.6, AzureRM provider 5.2.0, no Azure
credentials. Outputs of the latest run are on the `ci-results-terraform` branch under `aca-vs-aks-regulated/`.

| Check | Terraform | OpenTofu |
| --- | --- | --- |
| `validate` against the provider schema, both modules | valid | not run separately |
| Container Apps module tests | 6 passed | 6 passed |
| AKS module tests | 8 passed | 8 passed |
| Decision script tests | 9 of 9 | |

| Module | Resources | Arguments set | Lines of HCL |
| --- | --- | --- | --- |
| Container Apps | 3 | 50 | 78 |
| AKS Standard | 3 | 72 | 106 |

Seven baseline controls are reported by both modules. Container Apps configures all seven. The AKS module
configures six: encryption between services inside the cluster is not a cluster setting, and needs a service
mesh or the Advanced Container Networking Services option, neither of which is in this module.

The Container Apps figure includes the application itself. The AKS figure does not: the workload's Deployment,
Service, NetworkPolicy, ServiceAccount and role bindings are Kubernetes manifests on top of the 106 lines.

## Not verified

Nothing was applied, so no claim is made that Azure accepts either configuration, that a private cluster with
this identity setup provisions, or that the resulting platforms are isolated. The ownership ledger and the
decision rules are a reading of Microsoft's documentation, not a statement by Microsoft.
