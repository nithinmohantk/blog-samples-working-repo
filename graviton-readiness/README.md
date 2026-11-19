# graviton-readiness

Companion code for the dataa.dev article *Moving to Graviton4: What to Check, How to Measure, How to Migrate* (25 March 2026).

Two pre-flight checks that find the usual blockers before any node moves to arm64:

| File | What it checks |
| :--- | :--- |
| `check_images.py` | Reads each image's manifest from Amazon ECR and reports whether it includes `linux/arm64`. Handles OCI image indexes, Docker manifest lists (skipping attestation entries) and single-platform images. |
| `check_wheels.py` | Reads `name==version` pins and asks PyPI whether each release ships a pure-Python or `aarch64` wheel. Packages with only an sdist will compile during the arm64 image build. |

## Use

```bash
pip install boto3==1.42.55
python check_images.py orders-api:1.42.0 billing-worker:2026.03.1   # needs ecr:BatchGetImage, ecr:GetDownloadUrlForLayer
python check_wheels.py requirements.txt                             # needs outbound HTTPS to pypi.org
```

Both exit 1 if anything needs attention, so they can gate a pipeline.

Example output of `check_wheels.py`:

```
numpy                          2.2.3           aarch64      ok
psycopg2                       2.9.10          sdist-only   CHECK
psycopg2-binary                2.9.10          aarch64      ok
requests                       2.32.3          pure         ok
```

## Tests

```bash
pip install boto3==1.42.55 pytest==9.0.2
python -m pytest -q
```

13 tests: ECR calls through botocore's Stubber (validated against the ECR API model in boto3 1.42.55), and the wheel classifier and requirements parser. The example output above was produced against live PyPI.

## Limits

- Private package indexes and internal wheels are reported as `not-on-pypi`; check them against your own index.
- Neither script finds architecture-specific code inside your application (inline assembly, x86 intrinsics, bundled native binaries). Build and test on arm64 for that.
