# C# 15 union types in a domain model

Sample for the dataa.dev article "C# 15 Union Types in a Real Domain Model: Dispensed, Rejected or Referred".

A dispensing decision for a prescription has three outcomes with different data. The sample models it as a
C# 15 union, shows the class-with-nullable-fields shape it replaces, and records what the compiler and runtime
do in the situations the feature overview does not cover.

Synthetic data only. Not clinically validated: the dispensing rules are illustrative.

| Path | What it is |
| --- | --- |
| `src/Prescribing` | The union, the decision function, three exhaustive handlers, and the legacy shape |
| `tests/SelfTest` | 19 checks, and a JSON Lines export of the outcomes |
| `whatif/AddCase` | The same handlers compiled against a union with a fourth case. Expected to fail |
| `python/consume_outcomes.py` | A non-.NET consumer of the exported JSON, with tests |
| `experiments` | Fifteen small programs, each asking one question of the compiler or runtime |
| `run_experiments.sh`, `verify.sh`, `ci.sh` | What the workflow runs |

## Run

Needs the .NET 11 SDK (and the .NET 10 runtime for one experiment) and Python 3.11 or later.

    ./verify.sh out            # tests, Python consumer, and the build that must fail
    ./run_experiments.sh out/experiments

## What was observed

GitHub Actions, `ubuntu-latest`, SDK 11.0.100, commit `f19a73d`:
<https://github.com/nithinmohantk/blog-samples-working-repo/actions/runs/43279382000>. Outputs of the latest run
are on the `ci-results-dotnet11` branch under `unions/`.

* Self-test 19 of 19. Python consumer tests 7 of 7; it classified the five exported outcomes as 1 dispensed,
  3 rejected, 1 referred.
* Adding a fourth case made the build fail with CS8509 at all three switches in `OutcomeHandlers.cs`.

| Question | Result |
| --- | --- |
| What does a union compile to? | A struct of 8 bytes with one `object` field, a constructor per case, `Value`, `[Union]`, `IUnion` |
| A switch that misses a case | Warning CS8509, not an error |
| A default union, switch without a `null` arm | `SwitchExpressionException` at run time |
| `Equals` on two unions holding equal records | `true`; a `HashSet` keeps one |
| `==` on two unions | Does not compile: CS0019 |
| `ToString()` | The union's type name, not the case |
| `union Amount(int, decimal)` | 24 bytes allocated per create-and-match |
| Hand-written `[Union]` struct with `TryGetValue` | 0 bytes; the struct is 24 bytes instead of 8 |
| Union wrapping an existing object | 0 bytes |
| JSON write | The case's own shape, no wrapper or discriminator |
| JSON read without a classifier | `JsonException`: ambiguous |
| JSON read with the structural classifier | Works when cases differ by property names; unknown shape is a `JsonException` |
| Two cases with the same properties | `NotSupportedException` from the classifier |
| JSON `null` | A default union |
| `union Validated<T>(T, Failure)` with `T = Failure` | Does not compile: CS0457 |
| Closed record hierarchy, missing case | Warning CS8509 |
| Closed hierarchy with `InferClosedTypePolymorphism` | JSON carries a `$type` discriminator and round-trips |
| Declaring a union in a `net10.0` project | Fails: `IUnion` and `UnionAttribute` are missing |
| The same with those two types declared by hand | Compiles and runs on .NET 10.0.15 |
| A C# 14 project using a union from a C# 15 library | Constructor and `Value` work; conversion and patterns are CS9327 |

Not covered: ASP.NET Core model binding and OpenAPI output for unions, source-generated JSON, Native AOT,
F# interop, and performance beyond the allocation counts above.
