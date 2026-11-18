# Agentic UI with Blazor and .NET 11: an order desk you can test without a model

Sample for the dataa.dev article "[Building an Agentic UI with Blazor and .NET 11: Streaming, Tool Cards, Approvals and Shared State, Tested Without a Model](https://www.dataa.dev/2026/11/18/building-an-agentic-ui-with-blazor-and-dotnet-11/)".

A second article uses the same sample: "[Agent Framework Hosting vs a Hand-Built AG-UI Endpoint in .NET 11: One Blazor UI, Two Servers, the Same Tests](https://www.dataa.dev/2026/11/25/agent-framework-hosting-vs-hand-built-ag-ui-endpoint-dotnet-11/)".

A Blazor Web App (interactive server) talks to an agent service over the AG-UI protocol. The agent
looks up orders, drafts replies into a panel the user can edit, and prepares refunds that a person
approves. The model is a scripted stand-in, so every run is the same and nothing needs a key.
All orders and customers are invented.

| Path | What it is |
| --- | --- |
| `src/Desk.Core` | The agent as an `IChatClient` pipeline: `ScriptedModel`, function invocation, three tools, and the `Ledger` that stands in for a payment system |
| `src/Desk.Agent` | ASP.NET Core service with one AG-UI endpoint (`AGUI.Server`), server-side verification of approvals, and a wire log for tests |
| `src/Desk.AgentFramework` | The same service on Microsoft Agent Framework hosting: `MapAGUIServer`, a session store, and two small agent wrappers |
| `src/Desk.Web` | Blazor Web App using `Microsoft.AspNetCore.Components.AI`: message list, a typed tool card, default approval buttons, a shared-state panel, a Stop button |
| `tests/Desk.Tests` | 48 tests in three layers: the pipeline alone, each service over AG-UI on an in-memory server (the same test class runs against both), the component in bUnit. `FrameworkMatrixTests` records what each framework setting does |
| `e2e/run.py` | Layer four: Chromium (Playwright) against the web app and an agent service, nine steps, with screenshots. The workflow runs it once per agent service |
| `ci.sh` | Everything the workflow runs |

## Run

    ./ci.sh out          # .NET 11 SDK and Python 3; installs Playwright's Chromium

    # or by hand, in two terminals (Development, so static web assets are served from the build)
    ASPNETCORE_ENVIRONMENT=Development dotnet run --project src/Desk.Agent --urls http://127.0.0.1:5101
    ASPNETCORE_ENVIRONMENT=Development AGENT_URL=http://127.0.0.1:5101 dotnet run --project src/Desk.Web --urls http://127.0.0.1:5100

To put the framework host behind the same web app, start `src/Desk.AgentFramework` in place of `src/Desk.Agent`.

Then ask: `Where is order O-1001?`, `Refund order O-1003`, `Draft a reply for order O-1001`, `Explain the refund policy`.

## Versions

.NET SDK 11.0.100; `Microsoft.AspNetCore.Components.AI` 0.1.0-preview.1.26466.103 (experimental; net11.0 only);
`AGUI.Client`, `AGUI.Server`, `AGUI.Formatting` 1.0.1; `Microsoft.Extensions.AI` 11.0.0; bUnit 2.15.2.
`Microsoft.Agents.AI.Hosting.AGUI.AspNetCore` 1.28.0-preview.261106.1 (with `Microsoft.Agents.AI` 1.28.0). That package asks for
`AGUI.Server` 1.0.0 and `Microsoft.Extensions.AI` 10.11.0; the workflow runs the wire tests on those versions as well as on the pinned ones.
Pin the Blazor AI package: a floating prerelease version resolves to `11.0.0-preview.7`, an older build that sorts higher.

## What was verified

GitHub Actions, `ubuntu-latest`. Transcripts, wire traces, screenshots and JSON for the latest run are on the
`ci-results-agentic-ui-blazor` branch.

## What this does not show

- No language model. `ScriptedModel` decides from keywords. It tests everything around a model and nothing about one.
- No authentication on either service. The agent endpoint must not be reachable by browsers or other untrusted callers.
- `PendingApprovals`, the framework host's session store and the `Ledger` are in memory, for one instance.
- The framework host's session store runs without isolation by caller, because nothing here has an identity.
- Blazor WebAssembly and Auto render modes were not tried. With them the browser would call the agent endpoint itself.
- Agent Framework was read through its public API and its behaviour under test, not its source. The settings matrix describes one preview build.
- The Blazor AI components are a preview. Names and behaviour will change.
