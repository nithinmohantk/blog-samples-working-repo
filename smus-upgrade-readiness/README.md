# SageMaker AI domain: Unified Studio upgrade-readiness report

Sample code for the dataa.dev article *Amazon SageMaker Unified Studio: What Changes for MLOps Teams on AWS* (27 March 2026).

`readiness.py` reads a SageMaker AI domain and reports what to review before upgrading it into Amazon SageMaker Unified Studio:

| Finding | Severity | Why |
| :--- | :--- | :--- |
| Active Studio Classic apps (`JupyterServer`, `KernelGateway`) or a Classic default landing URI | blocker | The Unified Studio upgrade starts from SageMaker Studio, not Studio Classic |
| `AppNetworkAccessType` is `VpcOnly` | review | Subnets and VPC endpoints for the project need checking first |
| Custom images attached to JupyterLab or KernelGateway | review | Launch each in a test space first |
| Lifecycle configurations attached | review | Run them in a test space first |
| Active Canvas or RStudio apps | review | Confirm how those users reach the tool after the upgrade |
| Domain already has `UnifiedStudioSettings.ProjectId` | info | Already linked |

The script is read-only. It calls `DescribeDomain`, `ListApps`, `ListUserProfiles` and `ListSpaces`, follows pagination, and uses adaptive retries. Exit code 0 means no blockers, 1 means at least one blocker, 2 means an AWS or SDK error.

## Run

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python readiness.py --domain-id d-xxxxxxxxxxxx --region eu-west-1 > report.json
```

The caller needs `sagemaker:DescribeDomain`, `sagemaker:ListApps`, `sagemaker:ListUserProfiles` and `sagemaker:ListSpaces`.

## Test

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

## What was verified

- Five tests pass with Python 3.13 and `boto3==1.42.76` (released 25 March 2026). The tests use botocore's `Stubber`, which validates every request and response against the SageMaker service model in that release, so operation names, parameter names and the `UnifiedStudioSettings` structure match the API as published then.
- Pagination is tested across two pages; apps in `Deleted` status are ignored.
- `test_update_domain_request_shape_is_valid` checks the `UpdateDomain` request with `DomainSettingsForUpdate.UnifiedStudioSettings` that links a domain to a Unified Studio project, and that a misspelled field is rejected. The script itself never sends it.
- Not verified here: running against a real AWS account, or the upgrade itself.
