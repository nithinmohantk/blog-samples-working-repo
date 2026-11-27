# DynamoDB bulk put items against BatchWriteItem and import from S3

Sample for the dataa.dev article on Amazon DynamoDB bulk put items (generally available
5 November 2026). It loads the same 1 million items (about 1 KB each, one GSI) four ways and
records time, cost basis and side effects:

| Step | What it does |
| --- | --- |
| `setup` | Checks the bulk put items API answers in the Region, creates a USD 20 budget alert (if `EMAIL` is set), an S3 bucket and four on-demand tables, all tagged `project=ddb-bulkput-blogtest` |
| `data` | Generates 16 gzip JSON Lines files in DynamoDB JSON (`bench/data.py`), a 100,000-item insert-only set and two files with planted errors, and uploads them |
| `batchwrite` | BatchWriteItem from 16 threads with unprocessed-item retries and full-jitter backoff (`bench/batchwrite.py`) |
| `standard` | Bulk put items, Standard tier, while an application thread does PutItem and GetItem on the same table; latency before, during and after |
| `rerun` | Bulk put items again with `attribute_not_exists(pk)` on 100,000 items that already exist |
| `accelerated` | Bulk put items, Accelerated tier, into an empty table |
| `import` | ImportTable into a new table |
| `errors` | Bulk put items on files with invalid records and a broken line |
| `verify` | Item counts, table write metrics during the imports, contents of the S3 reports |
| `teardown` | Deletes the tables, bucket and budget and lists anything left |

## Run it (AWS CloudShell)

```bash
git clone https://github.com/nithinmohantk/blog-samples-working-repo.git
cd blog-samples-working-repo/ddb-bulk-put-items
EMAIL=you@example.com ./run.sh
./run.sh teardown
```

`run.sh` creates a Python 3.13 environment with uv (boto3 1.44 needs Python 3.10 or later), runs
the offline tests, then the steps. Default Region `eu-west-1`; set `AWS_REGION` to change it.
Results go to `results/`.

## Tests

`tests/test_bench.py` runs without AWS: data shape, BatchWriteItem retries and the
StartBulkPutItems request, checked against the botocore 1.44.12 service model with Stubber.

## What was verified

Two runs in AWS CloudShell, eu-west-1, on 26 and 27 November 2026 with boto3 1.44.12; the figures
are in `results/run-2026-11-27.md`. The first run stopped when CloudShell timed out during the
Standard bulk put (the operation itself finished and was collected with
`python -m bench.cli resume`). The second run reused the tables, so its BatchWriteItem and Standard
loads were overwrites of identical items; both cases are reported. The application-traffic thread
was slowed by client-side stalls of about 1 s, so its latency figures show only that the median
did not change and that there were no errors or throttling.
