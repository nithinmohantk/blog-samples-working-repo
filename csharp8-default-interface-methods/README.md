# C# 8.0: default implementations in interfaces

Sample code for the article "[C# 8.0 New Feature: Interface Default Implementation for Methods](https://www.dataa.dev/2018/12/01/c-8-0-new-feature-interface-default-implementation-for-methods/)".

Every project is compiled with `<LangVersion>8.0</LangVersion>` (set once in `Directory.Build.props`), so the compiler accepts only what C# 8.0 accepts.

| Path | What it shows |
| --- | --- |
| `Vehicles/` | The article's example: one method with a default body, one class that uses it and one that replaces it |
| `Evolve/` | Adding a method to an interface that already has implementers, without breaking them |
| `experiments/01-call-through-class/` | Calling the default method through the class type does not compile (CS1061) |
| `experiments/02-two-defaults-clash/` | Two interfaces override the same default and a class implements both (CS8705) |
| `experiments/03-most-specific-wins/` | How the clash is settled, and which body each class gets |
| `experiments/04-csharp-7-3/` | The same interface compiled as C# 7.3 (CS8370) |

```bash
dotnet run --project Vehicles
dotnet run --project Evolve
./ci.sh out      # runs everything and checks the three expected compiler errors
```

The feature needs support from the runtime as well as the compiler, so it runs on .NET Core 3.0 and later and not on .NET Framework. The projects here target the SDK that builds them.
