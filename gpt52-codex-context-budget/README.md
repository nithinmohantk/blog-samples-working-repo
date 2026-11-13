# GPT-5.2-Codex: what fits in the context window, and what it costs

Sample for the dataa.dev article "[GPT-5.2-Codex: 400K Context, Image Input and Microsoft Foundry](https://www.dataa.dev/2026/02/01/gpt-5-2-codex-400k-context-window-multimodal-coding-and-azure-ai-foundry-integration/)".

Three things, none of which calls a model:

* a count of how many lines of real code fit in 400,000 tokens, using tiktoken on this repository;
* a cost model built on the published prices, for one request and for a session of questions about one repository;
* a client for the Responses API that keeps the repository part of the prompt identical between requests so that
  prompt caching can apply, tested through the official `openai` package against a local stand-in.

The stand-in applies the prompt-caching rules as OpenAI and Microsoft document them. It is a model of those rules,
not a copy of the service, and it answers every question with the same fixed text. To use the client for real,
give it a key for api.openai.com or the name of an Azure OpenAI resource in Microsoft Foundry.

| Path | What it is |
| --- | --- |
| `prices.json` | The published prices and limits, with their sources |
| `codex_budget/budget.py` | Token counting, the cacheable part of a prefix, room for output, session cost |
| `codex_budget/client.py` | `RepositorySession`: stable prefix first, question and image last, usage and cost back |
| `standin/server.py` | A local `POST /v1/responses` with the documented response shape and caching rules |
| `tests/run.py` | All checks |
| `ci.sh` | Installs `openai` and `tiktoken` as they stood on 1 February 2026 and runs the checks |

## Run

    ./ci.sh out

## Use against a real endpoint

    from codex_budget.client import RepositorySession, openai_client, foundry_client
    client = openai_client(os.environ["OPENAI_API_KEY"])
    # or: client = foundry_client("my-resource", os.environ["AZURE_OPENAI_API_KEY"])
