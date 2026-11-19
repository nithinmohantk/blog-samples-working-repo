"""Submit documents to Bedrock Data Automation and route the results by confidence.

submit()      starts an asynchronous BDA job with EventBridge notification.
handler()     is a Lambda handler for the "Bedrock Data Automation Job Succeeded"
              EventBridge event. It finds the job's job_metadata.json, reads the
              custom output for each document segment, and splits fields into
              accepted values and values that need a person to check them.
cost_per_page() prices custom output per page (blueprint fields above 30 cost extra).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any, Iterator
from urllib.parse import urlparse

log = logging.getLogger()
log.setLevel(logging.INFO)

CUSTOM_PAGE_PRICE = 0.040       # USD per page, blueprints with up to 30 fields
EXTRA_FIELD_PRICE = 0.0005      # USD per page for each field above 30
STANDARD_PAGE_PRICE = 0.010     # USD per page, standard output only


def cost_per_page(fields: int) -> float:
    return round(CUSTOM_PAGE_PRICE + max(0, fields - 30) * EXTRA_FIELD_PRICE, 6)


def submit(client: Any, *, input_uri: str, output_uri: str, project_arn: str,
           profile_arn: str, kms_key_arn: str | None = None) -> str:
    """Start an async job. The client token makes a retried submit of the same object idempotent."""
    kwargs: dict[str, Any] = {
        "clientToken": hashlib.sha256(input_uri.encode()).hexdigest()[:64],
        "inputConfiguration": {"s3Uri": input_uri},
        "outputConfiguration": {"s3Uri": output_uri},
        "dataAutomationConfiguration": {"dataAutomationProjectArn": project_arn, "stage": "LIVE"},
        "dataAutomationProfileArn": profile_arn,
        "notificationConfiguration": {"eventBridgeConfiguration": {"eventBridgeEnabled": True}},
    }
    if kms_key_arn:
        kwargs["encryptionConfiguration"] = {"kmsKeyId": kms_key_arn}
    return client.invoke_data_automation_async(**kwargs)["invocationArn"]


def _split(uri: str) -> tuple[str, str]:
    u = urlparse(uri)
    return u.netloc, u.path.lstrip("/")


def _read_json(s3: Any, bucket: str, key: str) -> dict[str, Any]:
    return json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())


def find_job_metadata(s3: Any, bucket: str, prefix: str, job_id: str) -> str:
    """Return the key of job_metadata.json for this job under the output prefix."""
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix.rstrip("/") + "/"):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if job_id in key and key.endswith("job_metadata.json"):
                return key
    raise FileNotFoundError(f"job_metadata.json for {job_id} not found under s3://{bucket}/{prefix}")


def confidences(explainability: Any, path: str = "") -> Iterator[tuple[str, float]]:
    """Yield (field path, confidence) for every field in a custom output explainability block."""
    if isinstance(explainability, list):
        for i, item in enumerate(explainability):
            yield from confidences(item, f"{path}[{i}]" if path else "")
    elif isinstance(explainability, dict):
        if isinstance(explainability.get("confidence"), (int, float)):
            yield path, float(explainability["confidence"])
            return
        for key, value in explainability.items():
            yield from confidences(value, f"{path}.{key}" if path else key)


def route(custom_output: dict[str, Any], threshold: float,
          required: set[str]) -> dict[str, Any]:
    """Split one document's custom output into accepted fields and fields to review."""
    scores = dict(confidences(custom_output.get("explainability_info", [])))
    low = sorted(p for p, c in scores.items() if c < threshold)
    missing = sorted(f for f in required if custom_output.get("inference_result", {}).get(f) in (None, ""))
    return {
        "blueprint": custom_output.get("matched_blueprint", {}).get("name"),
        "values": custom_output.get("inference_result", {}),
        "low_confidence": low,
        "missing_required": missing,
        "needs_review": bool(low or missing),
    }


def handler(event: dict[str, Any], context: Any = None, *, s3: Any = None, sqs: Any = None) -> dict[str, Any]:
    import boto3  # imported here so tests can inject stubbed clients

    s3 = s3 or boto3.client("s3")
    sqs = sqs or boto3.client("sqs")
    detail = event["detail"]
    if detail.get("job_status") != "SUCCESS":
        log.error(json.dumps({"job_id": detail.get("job_id"), "error": detail.get("error_message")}))
        _send(sqs, {"job_id": detail.get("job_id"), "reason": "job failed",
                    "error": detail.get("error_message"), "input": detail.get("input_s3_object")})
        return {"job_id": detail.get("job_id"), "documents": 0, "review": 1}

    threshold = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.85"))
    required = set(filter(None, os.environ.get("REQUIRED_FIELDS", "").split(",")))
    out = detail["output_s3_location"]
    meta_key = find_job_metadata(s3, out["s3_bucket"], out["name"], detail["job_id"])
    meta = _read_json(s3, out["s3_bucket"], meta_key)

    documents = review = 0
    for asset in meta.get("output_metadata", []):
        for segment in asset.get("segment_metadata", []):
            if segment.get("custom_output_status") != "MATCH":
                review += 1
                _send(sqs, {"job_id": detail["job_id"], "reason": "no blueprint match",
                            "segment": segment})
                continue
            bucket, key = _split(segment["custom_output_path"])
            result = route(_read_json(s3, bucket, key), threshold, required)
            documents += 1
            log.info(json.dumps({"job_id": detail["job_id"], "segment": key,
                                 "needs_review": result["needs_review"],
                                 "low_confidence": result["low_confidence"]}))
            if result["needs_review"]:
                review += 1
                _send(sqs, {"job_id": detail["job_id"], "custom_output": f"s3://{bucket}/{key}", **result})
    return {"job_id": detail["job_id"], "documents": documents, "review": review}


def _send(sqs: Any, body: dict[str, Any]) -> None:
    sqs.send_message(QueueUrl=os.environ["REVIEW_QUEUE_URL"], MessageBody=json.dumps(body, default=str))
