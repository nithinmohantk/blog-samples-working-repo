"""Checks the S3 Vectors model against the two worked examples on the AWS pricing page,
then prints the scenarios used in the article. Run: python test_cost_model.py"""
from vector_cost_model import (Workload, aurora_pgvector, hnsw_memory_bytes, opensearch_serverless,
                               s3_vectors, total, GIB)

# AWS pricing example 1: 40 indexes x 250K vectors, 1M queries, top 100  -> $11.38
ex1 = s3_vectors(Workload(indexes=40, vectors_per_index=250_000, top_k=100))
# AWS pricing example 2: 40 indexes x 12.5M vectors, 10M queries, top 100 -> $1,320.47
ex2 = s3_vectors(Workload(indexes=40, vectors_per_index=12_500_000, queries_per_month=10_000_000, top_k=100))
print("AWS example 1:", {k: round(v, 2) for k, v in ex1.items()}, total(ex1))
print("AWS example 2:", {k: round(v, 2) for k, v in ex2.items()}, total(ex2))
assert abs(total(ex1) - 11.38) / 11.38 < 0.01, total(ex1)
assert abs(total(ex2) - 1320.47) / 1320.47 < 0.01, total(ex2)
assert abs(ex1["query_processing"] - (1.93 + 1.44)) < 0.02
assert abs(ex2["query_processing"] - (19.26 + 953.36 + 48.26)) < 1.0

scenarios = {
    "A pilot: 1 index, 100K vectors, 20K queries, 60 active hours":
        Workload(indexes=1, vectors_per_index=100_000, queries_per_month=20_000, active_hours=60),
    "B siloed SaaS: 40 tenants x 250K, 1M queries, 220 active hours":
        Workload(indexes=40, vectors_per_index=250_000, active_hours=220),
    "C pooled: 1 index of 10M, 1M queries, 220 active hours":
        Workload(indexes=1, vectors_per_index=10_000_000, active_hours=220),
}
for name, w in scenarios.items():
    s3 = s3_vectors(w)
    print(f"\n{name}  (HNSW memory {hnsw_memory_bytes(w)/GIB:.1f} GiB)")
    print(f"  S3 Vectors                       {total(s3):>10,.2f}   processing {s3['query_processing']:.2f}")
    for label, parts in {
        "OpenSearch Serverless classic":    opensearch_serverless(w, next_gen=False),
        "OpenSearch Serverless next gen":   opensearch_serverless(w, next_gen=True),
        "Aurora pgvector, min 0.5 ACU":     aurora_pgvector(w, auto_pause=False),
        "Aurora pgvector, auto-pause":      aurora_pgvector(w, auto_pause=True),
    }.items():
        print(f"  {label:32} {total(parts):>10,.2f}   compute {parts['compute']:,.2f}  storage {parts['storage']:.2f}")
b = scenarios["B siloed SaaS: 40 tenants x 250K, 1M queries, 220 active hours"]
print("\nScenario B with half-precision vectors (2x compression):")
print("  OpenSearch Serverless next gen  ", total(opensearch_serverless(b, next_gen=True, compression=2)))
print("  Aurora pgvector, auto-pause     ", total(aurora_pgvector(b, auto_pause=True, compression=2)))
floor = opensearch_serverless(scenarios["A pilot: 1 index, 100K vectors, 20K queries, 60 active hours"], next_gen=False)
assert round(floor["compute"], 2) == 350.40        # the documented 2-OCU classic minimum
print("\nALL COST MODEL TESTS OK")
