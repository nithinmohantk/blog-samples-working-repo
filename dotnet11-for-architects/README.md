# .NET 11 for architects: evidence for an upgrade decision

Sample for the dataa.dev article ".NET 11 for Architects: What Changes a Design, and What Does Not".

Four small programs that turn release notes into observations: what the new library APIs do on real input,
what Runtime Async changes, what behaves differently from .NET 10, and whether a host can start .NET 11 at all.

Synthetic data only.

| Path | What it is |
| --- | --- |
| `probe` | Prints the public shape of the new APIs from the installed runtime, by reflection |
| `src/Tour` | Zstandard beside gzip and Brotli, `FullJoin`, JSON Lines, the one-call process API, `StringStream` |
| `src/AsyncStack` | One async program built with and without Runtime Async: live stack frames and allocations |
| `src/UpgradeCheck` | One program built for `net10.0` and `net11.0`: behaviour probes and timings |
| `python/check_cpu_baseline.py` | Does an x86-64 host meet the new minimum instruction set? With tests |
| `python/compare_runtimes.py` | Compares two `UpgradeCheck` reports |
| `ci.sh` | Runs all of it; this is what the workflow calls |

## Run

Needs the .NET 11 SDK, the .NET 10 runtime for the comparison, and Python 3.11 or later.

    ./ci.sh out
    python python/check_cpu_baseline.py            # exit 1 means .NET 11 will not start on this host

## What was observed

GitHub Actions, `ubuntu-latest` (AMD EPYC 9V74), SDK 11.0.100, runtime 11.0.0 against 10.0.15, commit `044917c`:
<https://github.com/nithinmohantk/blog-samples-working-repo/actions/runs/43277042753>. The outputs of the latest
run are on the `ci-results-dotnet11` branch.

Behaviour that differs between the two runtimes (8 of 15 probes):

| Probe | .NET 10 | .NET 11 |
| --- | --- | --- |
| Empty `GZipStream`, bytes written | 0 | 20 |
| Empty `DeflateStream`, bytes written | 0 | 2 |
| Empty `ZLibStream`, bytes written | 0 | 8 |
| `unchecked((byte)300.7)` | 44 | 255 |
| `unchecked((sbyte)300.7)` | 44 | 127 |
| `unchecked((byte)-300.7)` | 212 | 0 |
| `unchecked((short)300.7e9)` | -1 | 32767 |
| `unchecked((ushort)-300.7)` | 65236 | 0 |

Runtime Async (preview, opt-in), same source built twice:

| | State machines | Runtime Async |
| --- | --- | --- |
| Live stack frames inside a three-level chain, before the first suspension | 17 | 5 |
| Live stack frames after resuming | 10 | 6 |
| Bytes allocated per call, chain that completes synchronously | 216 | 72 |
| Bytes allocated per call, chain that yields | 285 | 312 |

Compression of 1,380,748 bytes of JSON Lines (3,000 synthetic observations):

| Codec, level | Bytes | Compress, ms | Decompress, ms |
| --- | --- | --- | --- |
| gzip Fastest | 63,654 | 0.67 | 1.97 |
| gzip Optimal | 41,052 | 4.16 | 1.64 |
| gzip SmallestSize | 38,613 | 6.98 | 1.71 |
| Brotli Fastest | 39,039 | 0.88 | 1.04 |
| Brotli Optimal | 37,482 | 3.81 | 1.25 |
| Brotli SmallestSize | 20,420 | 2,471.41 | 2.12 |
| Zstandard Fastest | 34,421 | 0.48 | 1.32 |
| Zstandard Optimal | 40,717 | 0.64 | 1.82 |
| Zstandard SmallestSize | 25,096 | 1,059.72 | 2.87 |

`StringStream` is read-only and not seekable: `Length` throws `NotSupportedException`.

## What not to conclude

The timings are single runs on a shared machine and they do not repeat. Two consecutive runs of the same commit
family gave -59% and then +28% for the same async micro-benchmark between .NET 10 and .NET 11. Use the timing
harness on your own workload and hardware; do not quote these numbers as a performance claim.

Not covered: ASP.NET Core 11, EF Core 11, C# 15 language features (see `../csharp15-unions`), Native AOT, Windows,
Arm64, and any real service under load.
