# AWS Emulator: a lab notebook

Sample for the dataa.dev article "[AWS Emulator, Two Days In: A Lab Notebook](https://www.dataa.dev/2026/11/13/aws-emulator-two-days-in-a-lab-notebook/)".

AWS Emulator became generally available on 11 November 2026. This folder installs it from AWS's Debian
package, checks the signature, and runs a set of experiments against it. The same experiments then run
against moto, so the two can be compared like for like.

Nothing here calls AWS. No AWS account or real credential is involved, and the emulator's own per-run keys
are masked in every transcript.

| Path | What it is |
| --- | --- |
| `ci.sh` | Download, verify, install, start, and run everything below |
| `lab/tour.py` | Twenty-two experiments across S3, DynamoDB, SQS, SNS, EventBridge, Lambda, Step Functions, Secrets Manager, KMS, SSM, Kinesis, CloudFormation, EC2 and IAM |
| `lab/coverage.py` | One parameterless read call to every service boto3 knows |
| `lab/bench.py` | A thousand sequential DynamoDB writes and reads |
| `lab/instances.py` | Two emulators at once, and what survives a restart |
| `lab/scores.py` | Summarises the fidelity scores AWS publishes with each release |
| `lab/common.py` | Session set-up for either endpoint, and the result recorder |

## Run

    ./ci.sh out      # Debian or Ubuntu on x86_64, with sudo, curl, gpg, Python 3, the AWS CLI and Docker

## What was verified

GitHub Actions, `ubuntu-latest` (4 vCPU): AWS Emulator 1.0.341, AWS CLI 2.39.3, Python 3.13, boto3 1.44.2,
moto 5.2.5, Terraform 1.16.5 with AWS provider 6.73.0. Transcripts and JSON for the latest run are on the
`ci-results-aws-emulator` branch.

| Observation | Result |
| --- | --- |
| Package signature | Good signature; fingerprint matches the user guide |
| Package and binary | 176.5 MB download, 951 MiB binary |
| Start to healthy | 0.17 s |
| Resident memory | 290 MiB at start, 432 MiB after the tour, 638 MiB after the survey |
| Tour, emulator | 22 of 22 experiments ran to completion |
| Tour, moto | 21 of 22; the Step Functions execution stayed `RUNNING` |
| Reach | Of 436 services in boto3: 256 answered, 78 returned 501, 66 have no parameterless read, 36 other |
| DynamoDB, 1,000 sequential calls | Emulator p50 0.98 ms put, 0.97 ms get; moto 2.07 ms and 2.17 ms |
| Two instances | Separate state and separate keys |
| Restart | Files removed on stop; no buckets and a new key afterwards |
| Terraform | Apply and destroy of a Secrets Manager secret completed |
| Published fidelity scores, v1.0.341 | 26,157 of 43,465 scored tests pass (60.2%), across 355 services |

Where the emulator and moto differed in the tour:

| Experiment | AWS Emulator | moto |
| --- | --- | --- |
| DynamoDB table straight after `CreateTable` | `CREATING`; a write fails with `ResourceNotFoundException`; `ACTIVE` after 3 s | `ACTIVE` at once |
| DynamoDB table named `ab` | `ValidationException` with AWS's message | Accepted |
| SNS or EventBridge to SQS with no queue policy | Not delivered | Delivered |
| Step Functions execution | `SUCCEEDED` with output | Stays `RUNNING` |
| Lambda invoke | 109 ms, in an embedded interpreter with no host access | 14.1 s first (container), 0.6 s second |
| Unsigned request | Not served | Served |
| IAM user with no policy lists buckets | Allowed | Allowed |

## What this does not show

- No comparison against real AWS was run here. Statements about what AWS does come from AWS documentation.
- One run on one kind of machine. Timings are for that runner.
- The emulator is released several times a day. These results are for 1.0.341.
- The tour is twenty-two small cases. The published fidelity scores are the broader measure.
