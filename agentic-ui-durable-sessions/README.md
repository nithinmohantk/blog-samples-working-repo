# Agentic UI that survives a reload

Sample for the dataa.dev article "[Agentic UI That Survives a Reload: Persisting the Conversation and a Pending Approval in Blazor](https://www.dataa.dev/2026/12/16/agentic-ui-blazor-reload-persisted-conversation-approvals/)" (16 December 2026).
It follows [agentic-ui-blazor](../agentic-ui-blazor): the same order desk, where the conversation now has an address,
is kept in a journal, and comes back after a reload, a restart of either service, or in a second tab.

All orders and customers are invented. The model is a scripted stand-in: nothing needs a key or a cloud account.

| Path | What it is |
| --- | --- |
| `src/Desk.Web/Conversations` | `JournalStore` (SQLite), `JournalThread` (the preview's `IConversationThread`, kept on disk), `TurnRecorder` (writes a turn while it is still arriving), `DeskSession` (opens a conversation) |
| `src/Desk.Web/Components` | The Blazor Server UI. `RestoreOnLoad` rebuilds the conversation, `RestoredApproval` gives a restored approval buttons that work, `RunError` says when an approval was refused |
| `src/Desk.Agent` | The AG-UI agent service. Pending approvals are behind `IApprovalStore`, in memory or in SQLite |
| `src/Desk.Core` | The agent pipeline, the tools, and the payment stand-in, which can keep its refunds in a file |
| `tests/Desk.Tests` | 18 tests: the UI agent with a journal against the agent service on an in-memory server, where "a reload" is new objects for the same thread id |
| `e2e/run.py` | Chromium (Playwright): ten steps that reload the page, restart each service and open a second tab |
| `ci.sh` | Everything the workflow runs |

## Run

    ./ci.sh out          # .NET 11 SDK and Python 3; installs Playwright's Chromium

    # or by hand, in two terminals
    ASPNETCORE_ENVIRONMENT=Development DESK_DATA=./data dotnet run --project src/Desk.Agent --urls http://127.0.0.1:5121
    ASPNETCORE_ENVIRONMENT=Development DESK_DATA=./data AGENT_URL=http://127.0.0.1:5121 dotnet run --project src/Desk.Web --urls http://127.0.0.1:5120

Open http://127.0.0.1:5120. The address changes to `/c/<id>`: that is the conversation. Ask `Refund order O-1003`,
reload the page, and approve.

## Settings for the lab

| Setting | Default | What it does |
| --- | --- | --- |
| `DESK_DATA` | `data` under the project | Folder for `conversations.db`, `approvals.db` and `ledger.jsonl` |
| `DESK_DURABLE_APPROVALS` | `true` | `false` keeps pending approvals in memory, to see what a restart then costs |
| `DESK_RESTORED_APPROVAL_BUTTONS` | `true` | `false` leaves a restored approval with the component's own buttons, which send nothing |
| `DESK_COMPACT_JOURNAL` | `true` | `false` stores one row per streamed word |

## What this sample does not do

There is no sign-in. A conversation's address is a random 128-bit id and whoever has it can open the conversation.
Tie conversations to a person before using this with real data: [agentic-ui-wasm-auth](../agentic-ui-wasm-auth) shows that part.
The journal is not encrypted and nothing ever deletes it.

## Versions

.NET SDK 11.0.100; `Microsoft.AspNetCore.Components.AI` 0.1.0-preview.1.26466.103 (experimental);
`AGUI.Client`, `AGUI.Server`, `AGUI.Formatting` 1.0.1; `Microsoft.Extensions.AI` 11.0.0; `Microsoft.Data.Sqlite` 11.0.0.
`Microsoft.Extensions.Validation` is pinned to 11.0.0: the Blazor AI preview asks for a release candidate that NuGet
reports under advisory GHSA-m28h-pj36-4364.
