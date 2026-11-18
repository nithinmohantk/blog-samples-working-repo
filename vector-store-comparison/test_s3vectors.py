"""Offline check: every request is validated against botocore's s3vectors service model.
No AWS account is contacted. Run: python test_s3vectors.py"""
import boto3
from botocore.stub import Stubber

import s3vectors_tenant as t

client = boto3.client("s3vectors", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="y")
emb = [0.1] * t.DIMENSION

with Stubber(client) as stub:
    stub.add_response("create_index", {"indexArn": "arn:aws:s3vectors:us-east-1:123456789012:bucket/rag-vectors-prod/index/tenant-acme"}, {
        "vectorBucketName": t.BUCKET, "indexName": "tenant-acme", "dataType": "float32",
        "dimension": 1024, "distanceMetric": "cosine",
        "metadataConfiguration": {"nonFilterableMetadataKeys": ["text"]}})
    t.create_tenant_index("acme", client)

    stub.add_client_error("create_index", service_error_code="ConflictException")
    t.create_tenant_index("acme", client)                    # second onboarding call is a no-op

    chunks = [{"key": f"d1#{i}", "embedding": emb, "doc_id": "d1", "text": "..."} for i in range(501)]
    stub.add_response("put_vectors", {})                     # 500
    stub.add_response("put_vectors", {})                     # 1
    assert t.put_chunks("acme", chunks, client) == 501

    stub.add_response("query_vectors",
                      {"distanceMetric": "cosine", "vectors": [{"key": "d1#0", "distance": 0.12, "metadata": {"doc_id": "d1", "text": "..."}}]},
                      {"vectorBucketName": t.BUCKET, "indexName": "tenant-acme", "queryVector": {"float32": emb},
                       "topK": 8, "returnMetadata": True, "returnDistance": True,
                       "filter": {"doc_id": {"$eq": "d1"}}})
    assert t.search("acme", emb, doc_id="d1", client=client)[0]["key"] == "d1#0"
    stub.assert_no_pending_responses()

for bad in ("../other", "ACME", "a", "acme/index/tenant-globex"):
    try:
        t.index_name(bad)
    except ValueError:
        continue
    raise AssertionError(bad)

arn = t.tenant_policy("123456789012", "us-east-1")["Statement"][0]["Resource"]
print(arn)
assert arn.endswith("/index/tenant-${aws:PrincipalTag/TenantId}")
print("boto3", boto3.__version__, "- ALL S3 VECTORS TESTS OK")
