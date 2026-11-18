# EKS extended support: audit and cost outlook

Sample code for the dataa.dev article *EKS Extended Support Pricing: What $0.60 an Hour Means for Your Fleet from 1 April*.

From the April 2024 billing cycle an EKS cluster on a Kubernetes version in extended support pays $0.60 per
cluster-hour for its control plane instead of $0.10. This code lists every cluster, says whether its version is
in standard or extended support, prices the next twelve months day by day, lists the upgrade steps to 1.29 and
reports upgrade insights that are not passing.

Read-only: `eks:ListClusters`, `eks:DescribeCluster`, `eks:ListInsights`.

## What is here

| Path | What it does |
| --- | --- |
| `eks_support/calendar.py` | The EKS version calendar as published on 23 February 2024. The EKS API has no support-status field. |
| `eks_support/cost.py` | Daily rate ($0.10, or $0.60 in extended support from 1 April 2024), monthly cost, 12-month forecast, automatic upgrade at end of extended support. |
| `eks_support/upgrade_path.py` | Steps one minor version at a time, with the API versions each release removed. |
| `eks_support/audit.py` | The audit across Regions, including upgrade insights. |
| `tools/audit_account.py` | Command line for your own account. |
| `tools/demo_fleet.py` | A made-up eight-cluster fleet in moto, with three plans priced. |
| `tools/api_check.py` | What the installed botocore EKS model offers. |
| `tests/` | 14 tests: calendar boundaries, cost arithmetic, upgrade steps, audit on moto, insights with Stubber. |

## Run it

```bash
python tools/audit_account.py --regions eu-west-1 us-east-1 --out eks.json
```

## What was verified

GitHub Actions, Python 3.12, boto3/botocore 1.34.49, moto 5.0.2, pytest 8.0.1 (`--exclude-newer 2024-02-23`).
All 14 tests pass. Demo fleet output:

```text
Audit on 2024-02-24
cluster            region     ver   status    extended from  steps  Apr 24-Mar 25
sandbox            us-east-1  1.23  extended  2024-02-24         6        5256.00
payments-prod      eu-west-1  1.24  extended  2024-02-24         5        5256.00
payments-staging   eu-west-1  1.24  extended  2024-02-24         5        5256.00
data-prod          eu-west-1  1.25  standard  2024-05-01         4        4896.00
platform-tools     eu-west-1  1.26  standard  2024-06-01         3        4524.00
web-prod           us-east-1  1.27  standard  2024-07-01         2        4164.00
web-dev            us-east-1  1.28  standard  2024-11-01         1        2688.00
new-svc            us-east-1  1.29  standard  2025-03-01         0        1248.00

Plans, control plane only, April 2024 to March 2025
  Leave every cluster where it is                $ 33288.00
  Upgrade 1.23 and 1.24 to 1.25 by 31 March      $ 32208.00
  Every cluster on 1.29 by 31 March              $  9984.00

One cluster, April 2024 to March 2025, by the version it runs from 1 April
  1.24  $ 5256.00   months with extended support charges: 12
  1.25  $ 4896.00   months with extended support charges: 11
  1.26  $ 4524.00   months with extended support charges: 10
  1.27  $ 4164.00   months with extended support charges: 9
  1.28  $ 2688.00   months with extended support charges: 5
  1.29  $ 1248.00   months with extended support charges: 1

Upgrade steps from 1.24 to 1.29
  -> 1.25: policy/v1beta1 PodSecurityPolicy (no replacement API; use Pod Security Admission); batch/v1beta1 CronJob; discovery.k8s.io/v1beta1 EndpointSlice; events.k8s.io/v1beta1 Event; autoscaling/v2beta1 HorizontalPodAutoscaler; policy/v1beta1 PodDisruptionBudget; node.k8s.io/v1beta1 RuntimeClass
  -> 1.26: flowcontrol.apiserver.k8s.io/v1beta1 FlowSchema and PriorityLevelConfiguration; autoscaling/v2beta2 HorizontalPodAutoscaler
  -> 1.27: storage.k8s.io/v1beta1 CSIStorageCapacity
  -> 1.28: no API removals
  -> 1.29: flowcontrol.apiserver.k8s.io/v1beta2 FlowSchema and PriorityLevelConfiguration
```

## What was not verified

- No real account. moto 5.0.2 does not implement `ListInsights`; insights are tested with Stubber.
- Calendar dates for 1.25 to 1.29 were published as months; the code uses the first of the month.
- Control plane only: nodes, Fargate, add-ons and data transfer are not priced.
