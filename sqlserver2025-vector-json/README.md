# SQL Server 2025 for architects: the vector type and native JSON

Sample for the dataa.dev article "[SQL Server 2025 for Architects: The Vector Type and Native JSON](https://www.dataa.dev/2026/04/25/sql-server-2025-for-architects-the-vector-type-and-native-json/)".

A set of experiments run against the SQL Server 2025 container image. Each one either checks a result (exact
nearest-neighbour search against the same arithmetic in C#, the same answer from every way of querying JSON) or
records what the server says (limits, errors, which features need `PREVIEW_FEATURES`), with timings, pages read
and log written.

The vectors are synthetic: 50,000 points of 384 dimensions scattered around 64 centres. They are not embeddings
from a model, so recall and timing figures describe this data on this machine. The 50,000 order documents are
synthetic too. The `sa` password is generated when the script starts, used for one throwaway container and never
written to a file.

| Path | What it is |
| --- | --- |
| `sql/vector.sql` | Table, load, exact search, vector index and `VECTOR_SEARCH`, as named batches |
| `sql/json.sql` | Three column types for the same documents, lookups, indexes, updates and aggregates |
| `src/Lab/Program.cs` | Runs the batches in order, checks what can be checked and prints the rest |
| `src/Lab/Db.cs` | One connection; a server error is returned as a result; pages read come from `STATISTICS IO` |
| `src/Lab/Synthetic.cs` | The repeatable test data and the brute-force distance |
| `tools/pick_tag.py` | Finds the container tag built most recently on or before a given day |
| `ci.sh` | Starts the container and runs all of it |

## Run

Needs Docker and Python 3; the .NET SDK is installed into a temporary folder.

    ./ci.sh out

Against a server you already have:

    export LAB_SQL_CONNECTION='Server=...;User ID=...;Password=...;Encrypt=True'
    dotnet run --project src/Lab -c Release -- sql out

It drops and recreates a database named `Lab`.

## What the run produces

`versions.txt`, `tags.txt`, `transcript.txt`, `results.json` and `server-banner.txt`. The workflow
`.github/workflows/sqlserver.yml` pushes them to the `ci-results-sqlserver` branch.
