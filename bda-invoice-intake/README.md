# bda-invoice-intake

Sample code for the dataa.dev article *Amazon Bedrock Data Automation: Intelligent Document Processing Without the Pipeline Plumbing* (3 March 2026).

## What is here

| File | Purpose |
| --- | --- |
| `blueprint.py` | Builds a BDA document blueprint (draft-07 JSON schema with `inferenceType` and `instruction` per field) for supplier invoices, checks it against BDA's documented blueprint limits, and creates it in the DEVELOPMENT stage. |
| `invoice_blueprint.json` | The generated invoice blueprint. |
| `intake.py` | Submits documents with `InvokeDataAutomationAsync` (idempotent client token, EventBridge notification, optional KMS key); a Lambda handler for BDA job events that reads `job_metadata.json` and each document's custom output, and queues low-confidence, incomplete, unmatched or failed documents for review; a per-page cost function. |
| `template.yaml` | SAM template: EventBridge rule for the three BDA job events, the router function, a review queue and dead-letter queues. |
| `tests/` | 9 pytest tests. |

## Run the tests

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
```

## What has been verified

- Tested with Python 3.13, `boto3==1.42.55` (23 February 2026) and `pytest==9.0.2`. Every BDA, S3 and SQS call in the tests goes through botocore's Stubber, which validates requests and responses against the API models in that release.
- `template.yaml` passes cfn-lint 1.48.1.
- The cost test reproduces the examples on the Amazon Bedrock pricing page.
- Nothing has been run against a live AWS account. The output file layout (`job_metadata.json`, `inference_result`, `explainability_info`) follows AWS documentation and published examples, not a captured job, so check the router against your first real job output.
