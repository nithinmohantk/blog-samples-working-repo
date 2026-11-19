# irsa-to-pod-identity

Sample code for the dataa.dev article *Amazon EKS Pod Identity: When to Replace IRSA and How to Migrate* (1 May 2026).

## What is here

| File | Purpose |
| --- | --- |
| `migrate.py` | Scans Kubernetes manifests for service accounts annotated for IRSA and the workloads that use them; flags Windows node selectors and proxies without `NO_PROXY` entries for the Pod Identity Agent; adds the `pods.eks.amazonaws.com` statement to a trust policy while keeping IRSA; plans and creates Pod Identity associations, with optional cross-account target roles and session policies. |
| `examples/orders.yaml` | Two IRSA workloads: one ready to move, one blocked by its proxy settings. |
| `examples/abac-permissions.json` | A permissions policy that uses Pod Identity session tags. |
| `tests/` | 8 pytest tests. |

## Run

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
python migrate.py prod-eu examples
```

## What has been verified

- Tested with Python 3.13, `boto3==1.42.95` (23 April 2026), `pyyaml==6.0.3` and `pytest==9.0.2`. The EKS calls go through botocore's Stubber, which validates requests and responses against the EKS API model in that release.
- `examples/abac-permissions.json` is checked as valid JSON only; it was not run through IAM Access Analyzer.
- Nothing has been run against a live cluster or AWS account.
- The scanner cannot see Fargate profiles; it reminds you to check them.
