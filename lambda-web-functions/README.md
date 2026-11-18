# Lambda Web Functions: an HTTP server, a measurement and a cost model

Sample for the dataa.dev article "Lambda Web Functions: When a Function Becomes a Web Server".

| Path | What it is |
| --- | --- |
| `app/index.js` | An appointments API as a plain Node.js HTTP server with no dependencies. It listens where `AWS_LAMBDA_HTTP_ENDPOINT` says, which is all a Web Function requires |
| `app/test/server.test.js` | Eight tests with the built-in test runner |
| `app/measure.js` | Runs the server as its own process, drives load at it, and reads the server's CPU time from the operating system |
| `cost/model.py`, `cost/rates.json` | Monthly cost of one workload as a Web Function, an event function behind a function URL, the same behind an HTTP API, and App Runner |
| `cost/test_model.py` | Checks the model against the worked examples on AWS's pricing pages |

Synthetic data only.

## Run

    cd app && npm test && node measure.js       # Node.js 24 or later, Linux for measure.js
    cd cost && python test_model.py && python model.py

    # On AWS (not done for this article):
    aws lambda-web deploy --name appointments --code ./app

## What was verified

GitHub Actions, `ubuntu-latest`, Node.js 24.22.2, Python 3.13, commit `a9610cd`:
<https://github.com/nithinmohantk/blog-samples-working-repo/actions/runs/43338914911>. Outputs of the latest run
are on the `ci-results-aws` branch.

* Server tests: 8 of 8. Started as a process with `AWS_LAMBDA_HTTP_ENDPOINT` set, it answered its health check
  and exited with code 0 within 10 ms of `SIGTERM`.
* Cost model: 12 of 12 checks. It reproduces the four Web Functions examples on the Lambda pricing page to
  within one cent, and App Runner's example 2 to within the rounding AWS applies.

| Measurement, one server process | Requests | Sum of request durations | Server CPU time |
| --- | --- | --- | --- |
| Requests that wait 200 ms on I/O, 128 at a time | 1,280 | 275.75 s | 0.20 s |
| Requests that hash in a loop, one at a time | 20 | 8.67 s | 11.78 s |

A health check sent while one 3.06 s hashing request was running took 2.91 s to answer.

## Not verified

**Nothing was deployed to AWS.** The server follows the documented contract for Web Functions and was run
locally and in CI only. Cold starts, scaling, the 128-request concurrency limit, endpoint authentication and
real bills were not observed. The cost model uses list prices read from the AWS pricing pages on
13 November 2026 for US East (N. Virginia), excludes free tiers and data transfer, and assumes the memory
figures in `model.py`.
