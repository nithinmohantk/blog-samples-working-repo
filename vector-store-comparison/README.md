# Vector store comparison sample

Companion code for "Amazon S3 Vectors vs. OpenSearch Serverless vs. pgvector for RAG" (dataa.dev, 30 June 2026).

| File | Role | How it was checked |
| --- | --- | --- |
| `vector_cost_model.py` | Monthly cost models for the three stores | `test_cost_model.py`: S3 Vectors model reproduces both worked examples on the AWS pricing page to within 0.2% |
| `s3vectors_tenant.py` | Index-per-tenant on S3 Vectors, with an IAM policy template | `test_s3vectors.py`: requests validated offline against botocore's service model. Not run against AWS |
| `pgvector_rls.sql` | Pooled tenancy on PostgreSQL with row-level security | `test_rls.mjs`: executed in PGlite (PostgreSQL with pgvector, in-process) |

## Run

    python -m venv .venv && .venv\Scripts\activate
    pip install boto3
    python test_cost_model.py
    set AWS_DEFAULT_REGION=us-east-1 && python test_s3vectors.py

    npm install @electric-sql/pglite @electric-sql/pglite-pgvector
    node test_rls.mjs

## Read before using the numbers

* S3 Vectors is modelled as billed. OpenSearch Serverless and Aurora figures are capacity ESTIMATES:
  full-precision HNSW held in memory, 6 GiB per OCU, 2 GiB per ACU. Quantisation changes them a lot.
* The next-generation OpenSearch Serverless OCU rate was not on the pages I read; the model assumes
  the classic 0.24 USD per OCU-hour. Replace it with the published rate.
* The IAM policy that substitutes a session tag into the index ARN was not tested in an AWS account.
* The RLS test ran on PGlite's bundled PostgreSQL and pgvector, which are newer than the versions
  Aurora offered in June 2026. The SQL uses no version-specific features beyond HNSW.
