# .NET 10 on AWS Lambda: one function, three builds

Sample for the dataa.dev article "[.NET 10 on AWS Lambda: Managed Runtime, Native AOT and SnapStart](https://www.dataa.dev/2026/04/11/dotnet-10-on-aws-lambda-managed-runtime-native-aot-and-snapstart/)".

One small function, a price quote behind an API Gateway HTTP API event, published three ways from the same
source: for the `dotnet10` managed runtime, the same with ReadyToRun, and as a Native AOT executable for
`provided.al2023`. Each build is then run in the AWS Lambda base image, whose entry point is the Lambda Runtime
Interface Emulator, and invoked over HTTP.

Nothing is deployed. The timings are taken on the machine that runs the script and compare the builds with each
other; they are not Lambda cold-start figures. SnapStart cannot be emulated locally: its two hooks are registered
in `Program.cs` and the methods they call are tested on their own.

| Path | What it is |
| --- | --- |
| `src/Quotes.Function/QuoteHandler.cs` | The handler, the source-generated JSON contexts, and the two methods the SnapStart hooks call |
| `src/Quotes.Function/Program.cs` | The entry point shared by all builds, and the SnapStart hook registration |
| `src/Quotes.Function/Quotes.Function.csproj` | `-p:Flavour=jit`, `r2r` or `aot`; `-p:ReflectionJson=true` for the build that Native AOT cannot run |
| `tests/SelfTest` | Ten checks on the handler with no Lambda runtime involved |
| `events/` | Six API Gateway HTTP API (payload 2.0) events |
| `tools/build.sh` | Publishes every build inside Amazon Linux 2023 and records sizes, times and trim warnings |
| `tools/pick_image.py` | Finds the newest dated base-image tag on or before a given day |
| `tools/emulate.py` | Starts each build in the emulator, compares the answers and takes the timings |
| `ci.sh` | Runs all of it |

## Run

Needs Docker and Python 3. The .NET SDK is installed inside the build container.

    ./ci.sh out

To try one build by hand, after `ci.sh` has been stopped before its last line or `tools/build.sh` has been run:

    docker run --rm -p 9000:8080 -v "$PWD/out/publish/jit:/var/task:ro" public.ecr.aws/lambda/dotnet:10 Quotes.Function
    curl -s -d @events/1-quote.json http://localhost:9000/2015-03-31/functions/function/invocations

The Native AOT build goes in the OS-only image, which starts `/var/runtime/bootstrap`:

    docker run --rm -p 9000:8080 -v "$PWD/out/publish/aot:/var/runtime:ro" public.ecr.aws/lambda/provided:al2023 bootstrap

## What the run produces

`versions.txt`, `selftest.txt`, `build.txt`, `emulator.txt` and `emulator.json`, plus the publish logs. The
workflow `.github/workflows/lambda-dotnet.yml` pushes them to the `ci-results-lambda-dotnet` branch.
