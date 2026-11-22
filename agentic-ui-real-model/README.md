# Agentic UI with a real model behind it

Sample for the dataa.dev article "[A Real Model Behind the Blazor Agentic UI: 360 Conversations, Two Models and a Planted Instruction](https://www.dataa.dev/2026/12/09/agentic-ui-real-model-360-conversations-planted-instruction/)" (9 December 2026).
It follows [agentic-ui-blazor](../agentic-ui-blazor), where a scripted stand-in played the model so that everything around it could be tested.
Here the stand-in is replaced by a real model on an OpenAI-compatible endpoint, and a lab counts what the model does with the same three tools.

All orders and customers are invented. Without a key the sample still builds and its offline tests run on the stand-in.

| Path | What it is |
| --- | --- |
| `src/Desk.Core/ModelFactory.cs` | The one place that knows which model is used: endpoint, key and model name, or the stand-in |
| `src/Desk.Core/DeskAgent.cs` | The pipeline: tools, the tool loop with approvals, the meter, the model |
| `src/Desk.Core/ModelMeter.cs` | Adds the instructions to every model call and records messages, tokens and timings |
| `src/Desk.Core/Prompts.cs` | Three versions of the instructions: plain, guarded, fenced |
| `src/Desk.Core/DeskTools.cs` | The three tools, and what `get_order` does with customer-typed text: raw, fenced or hidden |
| `src/Desk.Agent`, `src/Desk.Web` | The AG-UI agent service and the Blazor UI from the first article |
| `tests/Desk.Tests/OfflineTests.cs` | 8 tests that need no key |
| `tests/Desk.Tests/RealModelLab.cs` | 18 scenarios, each a short conversation run several times against the real model, with checks code can make |
| `examples/` | The results of the run the article is written from |

## Run

    ./ci.sh out                                  # offline part only

    export MODEL_ENDPOINT=https://YOUR-RESOURCE.openai.azure.com/openai/v1/
    export MODEL_NAME=your-deployment            # or several: "deploymentA=label,deploymentB"
    export MODEL_API_KEY=...                     # from your secret store; do not paste it into a file
    LAB_RUNS=10 ./ci.sh out                      # 18 scenarios x 10 runs per model

    # the UI with the real model, in two terminals
    ASPNETCORE_ENVIRONMENT=Development dotnet run --project src/Desk.Agent --urls http://127.0.0.1:5101
    ASPNETCORE_ENVIRONMENT=Development AGENT_URL=http://127.0.0.1:5101 dotnet run --project src/Desk.Web --urls http://127.0.0.1:5100

Any endpoint that speaks the OpenAI chat API works. The GitHub workflow reads the same three names from a repository secret and two variables, and skips the lab when they are absent.

`DESK_PROMPT` (`guarded`, `plain`, `fenced`) and `DESK_NOTES` (`raw`, `fenced`, `hidden`) choose the instructions and what `get_order` does with customer text.

## Versions

.NET SDK 11.0.100; `Microsoft.Extensions.AI` and `Microsoft.Extensions.AI.OpenAI` 11.0.0; `OpenAI` 2.14.0; `AGUI.Server`, `AGUI.Client` 1.0.1.
