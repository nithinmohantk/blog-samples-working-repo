# HL7 v2 ADT to FHIR in .NET 10

Sample for the dataa.dev article "[HL7 v2 ADT to FHIR in .NET 10: Synthetic Messages, Validated Output](https://www.dataa.dev/2026/03/14/hl7-v2-adt-to-fhir-in-dotnet-10-synthetic-messages-validated-output/)".

A converter for six ADT trigger events (A01, A03, A04, A08, A11, A40) that turns each message into one FHIR R4
transaction. It has no package dependencies: the HL7 v2 reader and the FHIR JSON are plain .NET, and the HL7
validator in the build is what checks the output.

Every person, number, address and telephone number in `messages/` is invented. Identifier systems use the
2.999 example OID arc. This is a teaching sample: it is not clinically validated, it implements no national
profile, and it converts only the segments and fields listed in the article.

| Path | What it is |
| --- | --- |
| `src/AdtToFhir.Core/Hl7Message.cs` | Reader: delimiters from MSH, repetitions, components, escape sequences, explicit nulls |
| `src/AdtToFhir.Core/V2Time.cs` | HL7 v2 dates and times to FHIR, at the precision received |
| `src/AdtToFhir.Core/AdtMapper.cs` | One message to one transaction Bundle. No I/O: the same message gives the same Bundle |
| `src/AdtToFhir.Core/FhirApplier.cs` | Reads the server, decides duplicate, out of order or merged away, overlays the message on what exists, sends with `ifMatch` |
| `src/AdtToFhir.Core/AdtPipeline.cs`, `Ack.cs` | Message in, acknowledgement out |
| `messages/` | Twelve synthetic messages and the script that writes them |
| `tests/SelfTest` | Offline checks, then the messages applied to a FHIR server |
| `python/verify_server_state.py` | Reads what was left on the server with plain HTTP; shares no code with the converter |
| `python/validate_output.py` | Runs the HL7 validator over every Bundle that was sent; the build fails on an error |
| `python/check_codes.py` | Asks a terminology server about each SNOMED CT coding that was sent |
| `ci.sh` | Runs all of it |

## Run

    dotnet run --project tests/SelfTest -c Release -- messages out
    docker run -d -p 8082:8080 hapiproject/hapi:v8.0.0
    dotnet run --project tests/SelfTest -c Release -- messages out http://127.0.0.1:8082/fhir
    python python/verify_server_state.py out
    python python/validate_output.py validator_cli.jar out
    python python/check_codes.py out

The server run expects an empty server: it asserts totals.

## What was verified

GitHub Actions, `ubuntu-latest`, .NET SDK 10.0.201 (runtime 10.0.5) installed into a private directory, Python
3.13, HAPI FHIR 8.0.0 in Docker, HL7 validator 6.8.2 with a pinned checksum. Outputs of the latest run are on the
`ci-results-hl7v2` branch under `hl7v2-adt-to-fhir/`, including every Bundle as sent (`sent/`).

| Check | Result |
| --- | --- |
| Reader, dates and times, mapping, acknowledgements (no server) | 49 of 49 |
| Nineteen steps against the FHIR server, and the state they left | 35 of 35 |
| Independent check of the server state, from Python | 13 of 13 |
| HL7 validator on the 12 Bundles as sent | 0 errors, 105 warnings |
| HL7 validator on two resources built by copying v2 values across | 5 errors, as intended |
| SNOMED CT codings asked of tx.fhir.org with `$validate-code` | 2 of 2 valid, displays match |

Observed on HAPI FHIR 8.0.0: a transaction entry whose `ifMatch` names an old version fails the transaction with
HTTP 409; an update that changes nothing writes no new version; an absolute URL reference to a resource on the
same server is refused as an external reference (HAPI-0507).

The 105 warnings are: no narrative (46), a relative reference from a `urn:uuid` entry to a resource that is in
the Bundle under its server URL (24), codes from HL7 v2 tables used where the binding is extensible (33), and a
marital status carried as text (2).

The validator runs with `-tx n/a`. Validator 6.8.2 could not use tx.fhir.org for SNOMED CT in this pipeline (the
server refused its cache requests), which is why external codes are checked by a separate script.

## Not covered

Other trigger events (A02 is rejected by design), Z-segments (reported, not mapped), PD1, PV2, DG1, IN1, GT1,
MLLP transport, moving a retired record's encounters and allergies to the surviving record, removal of an
allergy that a later message no longer lists, national profiles, and performance.
