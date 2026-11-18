# ECS Express Mode, App Runner or Lambda for a small API: a cost model

Sample for the dataa.dev article "[ECS Express Mode, App Runner or Lambda for a Small API](https://www.dataa.dev/2026/04/04/ecs-express-mode-app-runner-or-lambda-for-a-small-api/)".

A cost model, and nothing else. No AWS resource was created for the article and none is created by this code. It
is arithmetic on list prices for US East (N. Virginia), with the traffic shape, the CPU per request and the
response size as stated assumptions.

| Path | What it is |
| --- | --- |
| `prices.json` | The list prices used, each with the pricing page it comes from |
| `model.py` | The three cost functions, the workload assumptions, and the tables |
| `test_model.py` | Checks the pricing functions against worked examples on the AWS pricing pages, and the model against its own arithmetic |
| `ci.sh` | Runs both |

## Run

    python -m unittest -v test_model
    python model.py

Change the fields of `Workload` in `model.py`, or the options in `OPTIONS`, to model your own API.

## What was verified

GitHub Actions, `ubuntu-latest`, Python 3.13. Outputs are on the `ci-results-costmodel` branch.

| Check | Result |
| --- | --- |
| Fargate pricing page, examples 1 and 2 (x86 and Arm) | reproduced to the cent |
| App Runner pricing page, lightweight API example (0.85 a day, 25.50 a month) | reproduced; the page rounds each day to cents |
| Lambda pricing page, mobile backend example (2.73 with the free tier) | reproduced to the cent |
| Model behaviour: floors, monotonic cost, shared load balancer, private subnets, break-even | 10 checks |

## What the model leaves out

The free tier (off by default), Savings Plans and other discounts, NAT gateways and VPC endpoints for private
subnets, AWS WAF, custom domains and certificates, container image storage and builds, provisioned concurrency on
Arm, Lambda cold-start duration, tax, and every price outside US East (N. Virginia). It models load balancer
capacity units pessimistically, with one new connection per request.

The App Runner active-time rule is an assumption: a minute with at least one request counts as an active minute
for one instance.
