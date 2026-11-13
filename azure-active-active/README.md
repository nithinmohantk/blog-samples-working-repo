# Active-active on Azure for a .NET API

Sample for the dataa.dev article "Active-Active on Azure for a .NET API: What Happens to the Write You Acknowledged".

A booking service in two regions, looked at from three sides: what each way of placing writes does during a
region outage (a deterministic simulation, in Python and in C#), what the API has to do so that a retry can
land in the other region (idempotent commands, a readiness rule), and the global tier in Terraform (Front
Door and a multi-region-write Cosmos DB account) tested against a mocked provider.

All data is synthetic. Nothing here is applied to a real subscription, and the simulation is a model: it
shows the shape of each trade-off, not Azure timings.

| Path | What it is |
| --- | --- |
| `src/ActiveActive.Core/BookingSimulation.cs` | Four write strategies on the same workload and the same outage |
| `src/ActiveActive.Core/IdempotentCommands.cs` | Runs a command once per idempotency key |
| `src/ActiveActive.Core/Readiness.cs` | What the global load balancer's probe is told |
| `src/ActiveActive.Api` | A minimal API using both; storage is process memory |
| `tests/SelfTest` | 23 checks; also writes the simulation results as JSON |
| `python/simulate.py` | The same model in Python. The two outputs must be identical |
| `python/drill.py` | A failover drill against two running instances of the API |
| `infra` | Front Door and Cosmos DB in Terraform, with tests against a mocked provider |
| `ci.sh` | Runs all of it |

## Run

    python python/simulate.py
    dotnet run --project tests/SelfTest -c Release
    cd infra && terraform init && terraform test

## What was verified

GitHub Actions, `ubuntu-latest`, .NET SDK DOTNETVER, Python 3.13, Terraform 1.16.3, OpenTofu 1.12.6, AzureRM
provider 5.2.0, no Azure credentials. Outputs of the latest run are on the `ci-results-terraform` branch under
`azure-active-active/`.

| Check | Result |
| --- | --- |
| Self-test | 23 of 23 |
| Python and C# simulations produce the same JSON | yes |
| Drill against two API instances | 9 of 9 |
| Patient references in the API logs | none |
| `terraform validate` | valid |
| Infrastructure tests, Terraform | TFTEST |
| Infrastructure tests, OpenTofu | TOFUTEST |

Simulation, seed 20261025: 2,000 attempts on 2,000 slots, replication lag 20 ticks, one region down from
tick 800 to tick 920, standby promoted 30 ticks into the outage.

| Region lost | Strategy | Accepted | Refused, region down | Taken back, no record | Taken back, compensated |
| --- | --- | --- | --- | --- | --- |
| North (the primary) | Multi-write, last writer wins | 1,265 | 0 | 9 | 0 |
| | Multi-write, first writer wins | 1,265 | 0 | 0 | 9 |
| | One writer per slot | 1,236 | 47 | 0 | 0 |
| | Active-passive | 1,259 | 30 | 16 | 0 |
| West (the standby) | Multi-write, last writer wins | 1,265 | 0 | 9 | 0 |
| | Multi-write, first writer wins | 1,265 | 0 | 0 | 9 |
| | One writer per slot | 1,235 | 73 | 0 | 0 |
| | Active-passive | 1,256 | 0 | 0 | 0 |

## What this does not show

- No Azure resource was created. Replication lag, failover times and conflict behaviour of Cosmos DB are
  taken from Microsoft's documentation, not measured here.
- The API keeps bookings and idempotency keys in process memory. In a deployment both live in the regional
  database, written together.
- The simulation delivers writes that were stranded in a failed region when it returns. A region that is
  lost for good loses them.
