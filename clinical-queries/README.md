# Querying clinical data three ways

Companion code for "Querying Clinical Data: AQL vs. FHIR Search vs. SQL on FHIR" (dataa.dev, November 2026).

| File | Role |
| --- | --- |
| `dataset.py` | Synthetic FHIR R4 dataset: 5 patients, blood pressures, HbA1c results, medication requests |
| `views.py` | Four SQL on FHIR ViewDefinitions |
| `view_runner.py` | A minimal ViewDefinition runner built on `fhirpathpy`. NOT a conformant runner |
| `queries.sql` | The four clinical questions as SQL over the resulting tables |
| `test_queries.py` | Runs views and SQL in DuckDB and checks every answer against one worked out directly from the resources |
| `dotnet/QueryClients.cs`, `dotnet/Program.cs` | C# clients for FHIR search (with paging) and AQL, tested against a stub HTTP handler |

## Run

    python -m venv .venv && .venv\Scripts\activate
    pip install -r requirements.txt
    python test_queries.py            # -> ALL QUERY TESTS OK

    cd dotnet && dotnet run           # .NET 10 SDK, no NuGet packages -> ALL CLIENT TESTS OK

Run by the author on Python 3.13 and .NET SDK 10.0.115 (warnings as errors).

## Read before using

* SYNTHETIC DATA ONLY.
* Executed: the ViewDefinitions and the SQL. NOT executed: the FHIR search URLs and the AQL in the
  article. There was no FHIR server and no openEHR repository; the C# clients were exercised against
  canned responses only.
* The runner supports resource, where, select/column, forEach, forEachOrNull, sibling cross joins,
  getResourceKey() and getReferenceKey(). No unionAll, nested select, constants or type checking.
  Use a conformant runner for real work.
* SQL on FHIR was a draft specification (2.1.0-pre) when this was written.
