"""Thin, policy-carrying wrappers over the Bedrock APIs the pipeline calls.

Model IDs, ARNs, bucket names and Regions are configuration. The wrappers
encode the two rules the design depends on:

  1. A customisation job only starts in an approved training Region, and only
     for a dataset whose gate certificate matches the file being submitted.
  2. Every question goes through the Guardrail and the current-documents
     filter, in the data Region.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from botocore.exceptions import ClientError

from .kb_metadata import current_documents_filter

log = logging.getLogger("bedrock_pipeline")

# Nova understanding models, Bedrock user guide "Custom model hyperparameters".
NOVA_LIMITS = {"epochCount": (1, 5), "learningRate": (1e-6, 1e-4), "learningRateWarmupSteps": (0, 100)}


@dataclass(frozen=True)
class Settings:
    data_region: str
    training_regions: frozenset[str]
    base_model_id: str
    role_arn: str
    output_s3_uri: str
    kms_key_arn: str
    knowledge_base_id: str
    generation_model_arn: str
    guardrail_id: str
    guardrail_version: str


class PolicyError(RuntimeError):
    """Raised before any API call when a request would break the design rules."""


def check_hyperparameters(params: dict[str, str]) -> None:
    for name, value in params.items():
        if name not in NOVA_LIMITS:
            raise PolicyError(f"hyperparameter {name} is not supported for Nova understanding models")
        low, high = NOVA_LIMITS[name]
        if not low <= float(value) <= high:
            raise PolicyError(f"{name}={value} outside {low}..{high}")


def submit_customization(bedrock, settings: Settings, certificate: dict, dataset: Path,
                         train_s3_uri: str, job_name: str, hyperparameters: dict[str, str]) -> str:
    region = bedrock.meta.region_name
    if region not in settings.training_regions:
        raise PolicyError(f"{region} is not an approved training Region")
    if certificate.get("personal_data") is not False:
        raise PolicyError("certificate does not state the dataset is free of personal data")
    digest = hashlib.sha256(dataset.read_bytes()).hexdigest()
    if digest != certificate.get("dataset_sha256"):
        raise PolicyError("dataset changed after it passed the gate")
    check_hyperparameters(hyperparameters)

    response = bedrock.create_model_customization_job(
        jobName=job_name,
        customModelName=f"{job_name}-model",
        roleArn=settings.role_arn,
        clientRequestToken=digest[:32],          # same dataset, same job: retries are safe
        baseModelIdentifier=settings.base_model_id,
        customizationType="FINE_TUNING",
        customModelKmsKeyId=settings.kms_key_arn,
        trainingDataConfig={"s3Uri": train_s3_uri},
        outputDataConfig={"s3Uri": settings.output_s3_uri},
        hyperParameters=hyperparameters,
        jobTags=[{"key": "dataset-sha256", "value": digest}, {"key": "personal-data", "value": "none"}],
    )
    log.info("customization job started", extra={"job_arn": response["jobArn"], "region": region})
    return response["jobArn"]


@dataclass(frozen=True)
class GroundedAnswer:
    text: str
    citations: tuple[str, ...]
    refused: bool
    latency_ms: int


def ask(agent_runtime, settings: Settings, question: str, retries: int = 3) -> GroundedAnswer:
    if agent_runtime.meta.region_name != settings.data_region:
        raise PolicyError(f"queries must run in {settings.data_region}")
    request = {
        "input": {"text": question},
        "retrieveAndGenerateConfiguration": {
            "type": "KNOWLEDGE_BASE",
            "knowledgeBaseConfiguration": {
                "knowledgeBaseId": settings.knowledge_base_id,
                "modelArn": settings.generation_model_arn,
                "retrievalConfiguration": {
                    "vectorSearchConfiguration": {"numberOfResults": 6, "filter": current_documents_filter()}
                },
                "generationConfiguration": {
                    "guardrailConfiguration": {
                        "guardrailId": settings.guardrail_id,
                        "guardrailVersion": settings.guardrail_version,
                    }
                },
            },
        },
    }
    for attempt in range(retries):
        started = time.perf_counter()
        try:
            response = agent_runtime.retrieve_and_generate(**request)
            break
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code not in ("ThrottlingException", "ServiceUnavailableException") or attempt == retries - 1:
                raise
            time.sleep(min(8.0, 0.5 * 2 ** attempt))
    latency = int((time.perf_counter() - started) * 1000)
    doc_ids = []
    for citation in response.get("citations", []):
        for ref in citation.get("retrievedReferences", []):
            doc_id = ref.get("metadata", {}).get("doc_id")
            if doc_id and doc_id not in doc_ids:
                doc_ids.append(doc_id)
    return GroundedAnswer(
        text=response["output"]["text"],
        citations=tuple(doc_ids),
        refused=response.get("guardrailAction") == "INTERVENED",
        latency_ms=latency,
    )


def guardrail_request(name: str, kms_key_arn: str) -> dict:
    """CreateGuardrail request. The built-in PII types include UK NHS numbers
    but no Irish identifiers, so IHI and PPSN are custom patterns. Guardrail
    regexes do not support lookaround, so these are simpler than identifiers.py.
    """
    return {
        "name": name,
        "description": "Irish health guidance assistant: no identifiers, no patient-specific advice",
        "kmsKeyId": kms_key_arn,
        "topicPolicyConfig": {
            "topicsConfig": [
                {
                    "name": "patient-specific-clinical-advice",
                    "definition": "Requests for a diagnosis, dose or treatment decision for a named or described individual patient.",
                    "examples": ["What dose should I give my patient who weighs 70 kg?"],
                    "type": "DENY",
                }
            ]
        },
        "sensitiveInformationPolicyConfig": {
            "piiEntitiesConfig": [
                {"type": "NAME", "action": "ANONYMIZE"},
                {"type": "PHONE", "action": "ANONYMIZE"},
                {"type": "EMAIL", "action": "ANONYMIZE"},
                {"type": "ADDRESS", "action": "ANONYMIZE"},
            ],
            "regexesConfig": [
                {"name": "ihi-gsrn", "description": "Individual Health Identifier, 18 digits",
                 "pattern": r"\b\d{18}\b", "action": "BLOCK"},
                {"name": "ihi-short", "description": "Individual Health Identifier, 10-digit form",
                 "pattern": r"\b\d{10}\b", "action": "BLOCK"},
                {"name": "ppsn", "description": "Personal Public Service Number",
                 "pattern": r"\b\d{7}[A-Wa-w][A-Za-z]?\b", "action": "BLOCK"},
            ],
        },
        "contextualGroundingPolicyConfig": {
            "filtersConfig": [
                {"type": "GROUNDING", "threshold": 0.85},
                {"type": "RELEVANCE", "threshold": 0.5},
            ]
        },
        "blockedInputMessaging": "This assistant answers questions about published HIQA and HSE guidance. "
                                 "It cannot process patient identifiers or give advice about an individual patient.",
        "blockedOutputsMessaging": "No answer could be given that is supported by the published guidance.",
    }
