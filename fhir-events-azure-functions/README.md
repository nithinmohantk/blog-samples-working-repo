# FHIR change events on Azure: an idempotent consumer

Sample for the dataa.dev article "FHIR Subscriptions and Events on Azure: Keeping Downstream Systems in Step".

An Azure Function on .NET 10 (isolated worker) that keeps a PostgreSQL projection of blood pressure readings
in step with a FHIR server, from change events in the Azure Health Data Services schema. Duplicates, late and
out-of-order deliveries, corrections and deletions all go through one rule: the stored version only moves forward.

Synthetic data only. Not clinically validated.

| Folder | What it is |
| --- | --- |
| `src/FhirEvents.Core` | Event parsing, the projection row, the handler. No packages |
| `src/FhirEvents.Functions` | Event Grid trigger, webhook endpoint, PostgreSQL store, FHIR reader |
| `tests/SelfTest` | 10 checks on the core with an in-memory store, including 120 concurrent deliveries |
| `tests/scenario.json` | The scripted scenario both implementations run |
| `python/projection_rule.py` | The same rule in Python, for a consumer that pulls from a queue |
| `python/replay_events.py` | Drives the running Function App with awkward event sequences and checks the projection |

## Run

    cd tests/SelfTest && dotnet run            # .NET 10 SDK, no packages
    python python/test_projection_rule.py      # Python 3.11+

    docker compose up -d --build               # Function App on :7071, PostgreSQL, one replay run
    # needs a FHIR server at http://localhost:8090/fhir (see ../clinical-queries/docker)

The keys in `local/host.secrets.json` and the database password in `docker-compose.yml` are throwaway values
for a loopback-only stack.

## What was verified

* Core self-test: 10 of 10 on the .NET 10 SDK. Python rule: same scenario, identical outcomes.
* `docker compose up -d --build` on Docker Desktop, 12 November 2026: the Function App built on the .NET 10
  SDK image and ran on the Azure Functions .NET 10 isolated image against HAPI FHIR 8.6.0 and PostgreSQL 16.
  `replay_events.py` passed 22 of 22, including a delivery through the Event Grid trigger's own endpoint.
* 120 concurrent deliveries for one resource (six versions, twenty copies each, shuffled) sent from a browser:
  one applied, 119 skipped, final row at version 6.

Not verified: Event Grid itself (the events were built by the script), Azure Health Data Services, managed
identity, dead-lettering, retries driven by Event Grid, and scale-out across several Function instances.
The NuGet references float within a major version, so a later build may resolve newer packages.
