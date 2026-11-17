# go-lambda-go1x-to-al2023

Sample for the dataa.dev article *Go on AWS Lambda After go1.x: Moving to provided.al2023* (6 January 2024).

One ordinary Go function (an API Gateway HTTP API handler that returns an order's status) built the ways a team builds it on the way from the `go1.x` runtime to `provided.al2023`, and run in the Lambda base images under the Runtime Interface Emulator.

| Path | What it is |
| :--- | :--- |
| `function/` | The handler (Go 1.21, `log/slog`, aws-lambda-go 1.43.0) and its unit tests |
| `events/` | Three hand-written API Gateway payload 2.0 events |
| `tools/build.sh` | Builds nine variants: go1.x style, renamed, norpc, stripped, arm64, cgo |
| `tools/emulate.py` | Runs each variant in the go1.x or provided.al2023 base image and invokes it |
| `tools/check_package.sh` | Pipeline gate: refuses a zip that will not start on provided.al2023 |
| `tools/pick_image.py` | Picks the newest dated base-image tag on or before a day |
| `finder/find_go1x.py` | Lists every function version, with aliases, still on an Amazon Linux 1 runtime |
| `infra/main.tf` | The function after the move: provided.al2023, arm64, published version behind an alias |
| `ci.sh` | Everything the workflow runs |

## Run

```
./ci.sh out        # needs Go 1.21, gcc, Docker with QEMU for arm64, Terraform 1.6 and Python 3.12
```

In GitHub Actions this is `.github/workflows/go-lambda.yml`; results are published to the branch `ci-results-go-lambda`.

## What was verified

Run in GitHub Actions with Go 1.21.5, Terraform 1.6.6 with AWS provider 5.31.0, Python 3.12 with boto3 1.34.14, moto 4.2.12 and pytest 7.4.4 (resolved as of 5 January 2024), against `public.ecr.aws/lambda/go:1.2024.01.05.16` (glibc 2.17) and `public.ecr.aws/lambda/provided:al2023.2024.01.05.14` (glibc 2.34).

| Scenario | Result |
| :--- | :--- |
| go1.x image, go1.x build (`main`, RPC compiled in) | works |
| provided.al2023, norpc build, x86_64 | works, same responses |
| provided.al2023, norpc build, arm64 under QEMU | works, same responses |
| provided.al2023, go1.x build renamed `bootstrap` | works, same responses |
| provided.al2023, go1.x package unchanged (`main`) | fails: `Runtime.InvalidEntrypoint`, no `/var/runtime/bootstrap` |
| provided.al2023, cgo build from the CI runner | works (needs GLIBC_2.34, the image has 2.34) |
| go1.x image, cgo build from the CI runner | fails: `GLIBC_2.34' not found` and `GLIBC_2.32' not found` |
| go1.x image, norpc build | works in the emulator (not checked on Lambda itself) |

Binary sizes (amd64): RPC unstripped 9,969,194 bytes; norpc unstripped 7,786,381; RPC stripped 6,832,128; norpc stripped 5,324,800; arm64 norpc stripped 5,046,272.

Also: 4 Go unit tests, 3 finder tests against moto, `terraform validate` on `infra/`, and the package gate on six packages (three accepted, three refused as expected).

## What was not verified

- Nothing was deployed to AWS. The emulator is not Lambda: start-up behaviour, billing and the go1.x runtime's real environment may differ.
- The go1.x base image's `/var/runtime/bootstrap` is an aws-lambda-go shim that contains `_LAMBDA_SERVER_PORT`; that a norpc build also answered there means the emulator also provided the Runtime API. Whether real go1.x does the same was not tested.
- arm64 ran under QEMU, so no timing is meaningful and none is reported.
- Container-image functions built on `lambda/go:1` are outside the finder (they have no `Runtime` field).
