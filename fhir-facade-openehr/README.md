# FHIR facade over an openEHR repository

Sample for the dataa.dev article "A FHIR Facade over an openEHR Repository on Azure".

An ASP.NET Core minimal API that serves blood pressure readings held in an openEHR repository (EHRbase) as
read-only FHIR R4 `Observation` resources, and enforces SMART on FHIR scopes on every request.

Synthetic data only. This is teaching material, not clinically validated software.

## What it does

| Request | Behaviour |
| --- | --- |
| `GET /fhir/metadata` | CapabilityStatement. Public. |
| `GET /fhir/Observation?patient=&code=http://loinc.org\|85354-9` | One patient's readings from one AQL query. Optional `date` (`ge`, `lt`), `_sort` (`date`, `-date`), `_count`, `_offset`. Any other parameter is a 400. |
| `GET /fhir/Observation/{id}` | One reading. The id is the EHR id followed by the composition id, 64 hexadecimal digits. |

Authorization: `patient/Observation.rs` (or v1 `.read`) with a `fhirUser` claim naming the patient, or
`system/Observation.rs` in `scp` or `roles`. The Entra ID spelling with dots (`patient.Observation.read`,
`patient.all.read`) is accepted. `user/` scopes and query-constrained scopes are refused.

## Layout

    src/FhirFacade/               the API (net10.0; needs the JwtBearer NuGet package)
    tests/FhirFacade.SelfTest/    43 checks against a stub repository replaying rows recorded from EHRbase
    client/test_client.py         Python test client: mints development tokens and checks the live facade
    Dockerfile, docker-compose.yml

## Run it locally

1. Start EHRbase from `../clinical-queries/docker` and load the synthetic patients (that folder's `live/RESULTS.md`
   describes the data). Each EHR needs a subject: `external_ref.id.value` = `p1`..`p5`, namespace `dataa-demo`.
2. From this folder:

       docker compose up -d --build

   This builds the facade on the .NET 10 SDK image, starts it on http://localhost:5080/fhir and runs the Python
   test client once. The client writes `client/report.json`.
3. Self-test without Docker, EHRbase or NuGet:

       cd tests/FhirFacade.SelfTest
       dotnet run                         # .NET 10 SDK

## What was verified, and how

| Check | Where it ran | Result |
| --- | --- | --- |
| `tests/FhirFacade.SelfTest` (43 checks, test authentication, stub repository replaying recorded EHRbase rows) | .NET 10 SDK, Linux | 43 of 43 |
| `docker compose up -d --build`: build on the `mcr.microsoft.com/dotnet/sdk:10.0` image with the real JwtBearer package | Docker Desktop, 12 November 2026 | Built and started |
| `client/test_client.py` against the running facade and EHRbase 2.39.0-SNAPSHOT | Docker Desktop, 12 November 2026 | 20 of 20 |
| The same matrix plus forged tokens (`alg: none`, wrong issuer), paging and read, sent from a browser | Same stack | All as expected |

Not verified: Microsoft Entra ID as the token issuer (the local run used development tokens signed with a shared
secret), any Azure deployment, load, and failure of the repository under the real host (the 502 path ran only in
the self-test).

What EHRbase 2.39.0 accepted and rejected while this was built:

* Filtering on `e/ehr_status/subject/external_ref/id/value` and `.../namespace` works, so a search is one query.
* `LIMIT $n` is a parse error. `LIMIT` and `OFFSET` take integer literals only.
* `ORDER BY <time> DESC, c/uid/value ASC` works.
* `c/uid/value LIKE ...` is not implemented. A composition is matched by its full version uid only, which is why
  a read first asks the composition endpoint (`HEAD`, `ETag`) for the latest version.
* The result set echoes the query with parameter values written in (`meta._executed_aql`). Do not log it.

## Configuration

| Setting | Meaning |
| --- | --- |
| `OpenEhr:BaseUrl` | openEHR REST base, ending in `/` |
| `OpenEhr:SubjectNamespace` | Namespace of the patient identifier in `EHR_STATUS.subject` |
| `Fhir:PublicBaseUrl` | The address clients use, for links in Bundles |
| `Auth:Authority` | OpenID Connect authority, for example `https://login.microsoftonline.com/{tenant}/v2.0` |
| `Auth:Audience` | The API's application ID URI or client id |
| `Auth:DevelopmentIssuer`, `Auth:DevelopmentSigningSecret` | Local testing only. The host refuses to start with the secret set outside `Development`. |

## Limits

* Blood pressure only, read only. No `Patient` resource, no `_include`, no `total` in Bundles.
* One blood pressure reading per composition. A composition with two fails the request.
* The facade sends no credentials to the repository. On Azure the repository must be reachable only from the facade.
* No retries, rate limiting or OpenTelemetry: each needs a package or a gateway and is left to the host platform.
