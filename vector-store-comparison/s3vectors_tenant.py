"""
s3vectors_tenant.py
Siloed multi-tenancy on Amazon S3 Vectors: one vector index per tenant inside one vector bucket.
The index is both the isolation boundary (IAM is granted per index ARN) and the billing boundary
(query processing is charged on the size of the index queried).
"""
import re
from typing import Any, Iterable

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

BUCKET = "rag-vectors-prod"
DIMENSION = 1024
PUT_BATCH = 500                                   # service limit per PutVectors call
TENANT_ID = re.compile(r"[a-z0-9][a-z0-9-]{1,40}")

_client = boto3.client(
    "s3vectors",
    config=Config(retries={"max_attempts": 8, "mode": "adaptive"}, connect_timeout=3, read_timeout=10),
)


def index_name(tenant_id: str) -> str:
    """The tenant id comes from the caller's verified identity, never from request text."""
    if not TENANT_ID.fullmatch(tenant_id):
        raise ValueError("invalid tenant id")
    return f"tenant-{tenant_id}"


def create_tenant_index(tenant_id: str, client: Any = _client) -> None:
    try:
        client.create_index(
            vectorBucketName=BUCKET,
            indexName=index_name(tenant_id),
            dataType="float32",
            dimension=DIMENSION,
            distanceMetric="cosine",
            # Stored and returned, but not filterable and not billed as query data processed.
            metadataConfiguration={"nonFilterableMetadataKeys": ["text"]},
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConflictException":      # already exists: onboarding is idempotent
            raise


def put_chunks(tenant_id: str, chunks: Iterable[dict], client: Any = _client) -> int:
    """chunks: {'key', 'embedding', 'doc_id', 'text'}. Batched: every PutVectors call has a minimum charge."""
    batch, written = [], 0
    for chunk in chunks:
        batch.append({
            "key": chunk["key"],
            "data": {"float32": chunk["embedding"]},
            "metadata": {"doc_id": chunk["doc_id"], "text": chunk["text"]},
        })
        if len(batch) == PUT_BATCH:
            client.put_vectors(vectorBucketName=BUCKET, indexName=index_name(tenant_id), vectors=batch)
            written, batch = written + len(batch), []
    if batch:
        client.put_vectors(vectorBucketName=BUCKET, indexName=index_name(tenant_id), vectors=batch)
        written += len(batch)
    return written


def search(tenant_id: str, embedding: list[float], top_k: int = 8,
           doc_id: str | None = None, client: Any = _client) -> list[dict]:
    request: dict[str, Any] = {
        "vectorBucketName": BUCKET,
        "indexName": index_name(tenant_id),
        "queryVector": {"float32": embedding},
        "topK": top_k,
        "returnMetadata": True,       # needs s3vectors:GetVectors as well as s3vectors:QueryVectors
        "returnDistance": True,
    }
    if doc_id:
        request["filter"] = {"doc_id": {"$eq": doc_id}}
    return client.query_vectors(**request)["vectors"]


def tenant_policy(account_id: str, region: str) -> dict:
    """Attach to the role the application assumes with a TenantId session tag.
    One policy serves every tenant. Verify the tag substitution in your account before relying on it."""
    return {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Action": ["s3vectors:QueryVectors", "s3vectors:GetVectors", "s3vectors:PutVectors",
                       "s3vectors:DeleteVectors"],
            "Resource": f"arn:aws:s3vectors:{region}:{account_id}:bucket/{BUCKET}"
                        "/index/tenant-${aws:PrincipalTag/TenantId}",
        }],
    }
